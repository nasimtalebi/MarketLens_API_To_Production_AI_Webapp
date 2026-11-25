"""Hybrid RAG QA module combining PostgreSQL financials, ChromaDB 10-K chunks, and Ollama."""
import argparse
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import ollama
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from search import MODEL_NAME, query_chroma

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

LLM_MODEL = "llama3.2"


def get_db_connection():
    """Connect to PostgreSQL using .env variables."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "marketlens"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def fetch_sql_context(ticker: Optional[str], year: Optional[int]) -> Dict[str, Any]:
    """Fetch structured financial metrics from PostgreSQL if ticker is provided."""
    if not ticker:
        return {"text": "No specific ticker provided for SQL financial metrics.", "rows": []}

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            """
        )
        tables = {row[0] for row in cur.fetchall()}

        rows_out: List[Dict[str, Any]] = []
        rows_text: List[str] = []

        candidate_tables = [t for t in ["financial_metrics", "financials", "filings"] if t in tables]
        for tbl in candidate_tables:
            cur.execute(
                f"SELECT * FROM {tbl} WHERE UPPER(ticker) = %s LIMIT 10",
                (ticker.upper(),),
            )
            cols = [desc[0] for desc in cur.description]
            for r in cur.fetchall():
                row_dict = dict(zip(cols, r))
                if year is not None and "fiscal_year" in row_dict and row_dict["fiscal_year"] != year:
                    continue
                cleaned = {k: (str(v) if v is not None else None) for k, v in row_dict.items() if v is not None}
                rows_out.append({"table": tbl, "data": cleaned})
                rows_text.append(f"[{tbl}] " + ", ".join(f"{k}: {v}" for k, v in cleaned.items()))

        cur.close()
        conn.close()

        if rows_text:
            return {"text": "\n".join(rows_text), "rows": rows_out}
        return {
            "text": f"No structured SQL rows matched ticker={ticker.upper()} year={year}.",
            "rows": [],
        }
    except Exception as exc:
        return {"text": f"[SQL lookup skipped/unavailable: {exc}]", "rows": []}


def detect_filters(question: str, ticker: Optional[str], year: Optional[int]):
    """Infer ticker or 4-digit year from the question if not explicitly passed."""
    inferred_ticker = ticker.upper() if ticker else None
    inferred_year = year

    if not inferred_ticker:
        m_tick = re.search(r"\b(AAPL|MSFT|NVDA|GOOGL|GOOG|AMZN|META|TSLA)\b", question.upper())
        if m_tick:
            inferred_ticker = m_tick.group(1)

    if inferred_year is None:
        m_yr = re.search(r"\b(201[89]|202[0-6])\b", question)
        if m_yr:
            inferred_year = int(m_yr.group(1))

    return inferred_ticker, inferred_year


def ask_structured(
    question: str,
    ticker: Optional[str] = None,
    year: Optional[int] = None,
    section: Optional[str] = None,
    top_k: int = 5,
    model: str = LLM_MODEL,
) -> Dict[str, Any]:
    """Run hybrid RAG and return answer, sources, and SQL context."""
    ticker, year = detect_filters(question, ticker, year)

    sql_info = fetch_sql_context(ticker, year)
    sql_context = sql_info["text"]

    embedder = SentenceTransformer(MODEL_NAME)
    q_vec = embedder.encode([question], normalize_embeddings=True).tolist()[0]
    res = query_chroma(q_vec, top_k, ticker, year, section)

    docs = res["documents"][0] if res.get("documents") else []
    metas = res["metadatas"][0] if res.get("metadatas") else []
    dists = res["distances"][0] if res.get("distances") else []

    excerpts: List[str] = []
    sources: List[Dict[str, Any]] = []

    for idx, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        meta = meta or {}
        tag = f"[{meta.get('ticker')} FY{meta.get('fiscal_year')} Item {meta.get('section')} | chunk {meta.get('chunk_index')}]"
        sim = round(1 - float(dist), 3)
        sources.append(
            {
                "rank": idx,
                "tag": tag,
                "ticker": meta.get("ticker"),
                "fiscal_year": meta.get("fiscal_year"),
                "section": meta.get("section"),
                "chunk_index": meta.get("chunk_index"),
                "similarity": sim,
                "preview": doc[:280].replace("\n", " "),
            }
        )
        excerpts.append(f"Source {idx} {tag}:\n{doc}")

    excerpts_block = "\n\n---\n\n".join(excerpts) if excerpts else "No matching 10-K text chunks found."

    system_prompt = (
        "You are MarketLens, a precise financial analyst assistant. "
        "Answer the user's question strictly using the provided PostgreSQL financial figures and 10-K filing excerpts. "
        "Always cite your sources inline using the bracket tags like [NVDA FY2024 Item 1A]. "
        "If the context does not contain enough information, state that clearly without guessing."
    )

    user_prompt = (
        f"Question: {question}\n\n"
        f"=== Structured Financial Data (PostgreSQL) ===\n{sql_context}\n\n"
        f"=== Relevant 10-K Filing Excerpts (ChromaDB) ===\n{excerpts_block}\n\n"
        "Provide a clear, well-structured answer with inline citations."
    )

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return {
        "answer": response["message"]["content"],
        "filters": {"ticker": ticker, "year": year, "section": section, "top_k": top_k},
        "model": model,
        "sources": sources,
        "sql_rows": sql_info["rows"],
    }


def answer_question(
    question: str,
    ticker: Optional[str] = None,
    year: Optional[int] = None,
    section: Optional[str] = None,
    top_k: int = 5,
    model: str = LLM_MODEL,
):
    result = ask_structured(
        question=question,
        ticker=ticker,
        year=year,
        section=section,
        top_k=top_k,
        model=model,
    )
    f = result["filters"]
    print(f"Filters -> ticker={f['ticker'] or 'ALL'}, year={f['year'] or 'ALL'}, section={f['section'] or 'ALL'}")
    print(f"Generating answer with Ollama ({result['model']})...\n")
    print("=" * 60)
    print(result["answer"])
    print("=" * 60)
    print("\nSources used:")
    for s in result["sources"]:
        print(f"  {s['rank']}. {s['tag']} (similarity={s['similarity']})")


def main():
    parser = argparse.ArgumentParser(description="Ask questions over 10-K filings and financial DB.")
    parser.add_argument("question", help="Question to ask")
    parser.add_argument("--ticker", help="Optional ticker filter (e.g., NVDA, AAPL, TSLA)")
    parser.add_argument("--year", type=int, help="Optional fiscal year filter (e.g., 2024)")
    parser.add_argument("--section", help="Optional 10-K section filter (1, 1A, 7)")
    parser.add_argument("-k", type=int, default=5, help="Number of retrieved chunks")
    parser.add_argument("--model", default=LLM_MODEL, help="Ollama model name")
    args = parser.parse_args()

    answer_question(
        question=args.question,
        ticker=args.ticker,
        year=args.year,
        section=args.section,
        top_k=args.k,
        model=args.model,
    )


if __name__ == "__main__":
    main()