"""Search Chroma vector DB by semantic similarity."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION = "filings"
MODEL_NAME = "all-MiniLM-L6-v2"


def query_chroma(
    query_vec: list,
    n_results: int,
    ticker: Optional[str],
    year: Optional[int],
    section: Optional[str],
) -> dict:
    payload = {
        "chroma_dir": str(CHROMA_DIR),
        "collection": COLLECTION,
        "query_vec": query_vec,
        "n_results": n_results,
        "ticker": ticker.upper() if ticker else None,
        "year": year,
        "section": section,
    }
    code = (
        "import json, sys, chromadb; "
        "p = json.load(open(sys.argv[1], encoding='utf-8')); "
        "conds = []; "
        "conds.append({'ticker': p['ticker']}) if p['ticker'] else None; "
        "conds.append({'fiscal_year': p['year']}) if p['year'] is not None else None; "
        "conds.append({'section': p['section']}) if p['section'] else None; "
        "where = conds[0] if len(conds) == 1 else ({'$and': conds} if len(conds) > 1 else None); "
        "col = chromadb.PersistentClient(path=p['chroma_dir']).get_collection(p['collection']); "
        "res = col.query(query_embeddings=[p['query_vec']], n_results=p['n_results'], where=where, include=['documents', 'metadatas', 'distances']); "
        "print(json.dumps(res))"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(payload, tf)
        tmp_path = tf.name
    try:
        out = subprocess.run(
            [sys.executable, "-c", code, tmp_path],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(out.stdout.strip().splitlines()[-1])
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    parser = argparse.ArgumentParser(description="Search 10-K filings in Chroma.")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--ticker", help="Company ticker, e.g. NVDA")
    parser.add_argument("--year", type=int, help="Fiscal year, e.g. 2024")
    parser.add_argument("--section", help="Section, e.g. 1, 1A, 7")
    parser.add_argument("-n", type=int, default=5, help="Number of results")
    args = parser.parse_args()

    model = SentenceTransformer(MODEL_NAME)
    q_vec = model.encode([args.query], normalize_embeddings=True).tolist()[0]
    res = query_chroma(q_vec, args.n, args.ticker, args.year, args.section)

    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    for idx, (doc, meta, dist) in enumerate(zip(docs, metas, dists), 1):
        sim = round(1 - dist, 3)
        print(f"\n#{idx} | {meta.get('ticker')} FY{meta.get('fiscal_year')} Item {meta.get('section')} | sim={sim}")
        print(doc[:400].replace("\n", " "))


if __name__ == "__main__":
    main()