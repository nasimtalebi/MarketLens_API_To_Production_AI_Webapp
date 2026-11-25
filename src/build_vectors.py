"""Extract Item 1, 1A, 7 from 10-K .htm files, chunk, embed, store in Chroma."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CHROMA_DIR = ROOT / "chroma_db"
COLLECTION = "filings"
MODEL_NAME = "all-MiniLM-L6-v2"

SECTIONS = ["1", "1A", "7"]
CHUNK_SIZE = 1000
OVERLAP = 200
MAX_UNIT = CHUNK_SIZE - OVERLAP
MIN_SECTION_CHARS = 1500
BATCH_SIZE = 64

ITEM_RE = re.compile(r"^[ \t]*item[ \t]+(\d{1,2}[A-C]?)\b", re.IGNORECASE | re.MULTILINE)
FY_RE = re.compile(
    r"for the fiscal year ended:?\s*([A-Za-z]+\s+\d{1,2},?\s+(\d{4}))", re.IGNORECASE
)
BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]


def html_to_text(html: str) -> str:
    """HTML -> plain text, one paragraph per line."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "ix:header"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.append("\n")
    for tag in soup.find_all(["td", "th"]):
        tag.append(" ")
    text = soup.get_text().replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def get_fiscal_year(text: str, path: Path):
    m = FY_RE.search(text[:20000])
    if m:
        return int(m.group(2))
    m = re.search(r"(20\d{2})", path.stem)
    if m:
        print(f"  [warn] fiscal year not found on cover page, using filename: {m.group(1)}")
        return int(m.group(1))
    return None


def extract_section(text: str, item: str):
    """Return the text of one Item. Uses the LAST match (the first is the table of contents)."""
    heads = [(m.start(), m.group(1).upper()) for m in ITEM_RE.finditer(text)]
    candidates = []
    for i, (pos, name) in enumerate(heads):
        if name != item:
            continue
        if i > 0 and heads[i - 1][1] == name:
            continue
        end = len(text)
        for pos2, name2 in heads[i + 1:]:
            if name2 != item:
                end = pos2
                break
        candidates.append(text[pos:end].strip())
    if not candidates:
        return None
    chosen = candidates[-1]
    if len(chosen) < MIN_SECTION_CHARS:
        longest = max(candidates, key=len)
        if len(longest) > len(chosen):
            print(f"  [warn] Item {item}: last match too short ({len(chosen)} chars), using longest match")
            chosen = longest
    return chosen


def split_units(line: str):
    """Keep a paragraph whole if it fits; otherwise split by sentence (then hard cut)."""
    if len(line) <= MAX_UNIT:
        return [line]
    units, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", line):
        while len(sent) > MAX_UNIT:
            if cur:
                units.append(cur)
                cur = ""
            units.append(sent[:MAX_UNIT])
            sent = sent[MAX_UNIT:]
        if cur and len(cur) + 1 + len(sent) > MAX_UNIT:
            units.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        units.append(cur)
    return units


def chunk_text(text: str):
    """~1000 chars per chunk, split on paragraphs, ~200 chars overlap."""
    units = []
    for line in text.split("\n"):
        units.extend(split_units(line))
    chunks, cur = [], ""
    for u in units:
        if cur and len(cur) + 1 + len(u) > CHUNK_SIZE:
            chunks.append(cur)
            tail = cur[-OVERLAP:]
            sp = tail.find(" ")
            cur = tail[sp + 1:] if sp != -1 else tail
        cur = f"{cur}\n{u}" if cur else u
    if cur:
        chunks.append(cur)
    return chunks


def upsert_in_subprocess(payload: dict) -> int:
    """Write chunks + embeddings in a clean Python process without torch loaded."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(payload, tf)
        tmp_path = tf.name

    writer_code = (
        "import json, sys, chromadb; "
        "p = json.load(open(sys.argv[1], encoding='utf-8')); "
        "client = chromadb.PersistentClient(path=p['chroma_dir']); "
        "col = client.get_or_create_collection(p['collection'], metadata={'hnsw:space': 'cosine'}); "
        "old = col.get(where={'$and': [{'ticker': p['ticker']}, {'fiscal_year': p['fiscal_year']}, {'section': p['section']}]}, include=[]); "
        "col.delete(ids=old['ids']) if old.get('ids') else None; "
        "col.upsert(ids=p['ids'], documents=p['documents'], embeddings=p['embeddings'], metadatas=p['metadatas']); "
        "print(col.count())"
    )
    try:
        res = subprocess.run(
            [sys.executable, "-c", writer_code, tmp_path],
            capture_output=True,
            text=True,
            check=True,
        )
        return int(res.stdout.strip().splitlines()[-1])
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    files = sorted(list(RAW_DIR.glob("*/10k/*.htm")) + list(RAW_DIR.glob("*/10k/*.html")))
    if not files:
        print(f"No .htm files found under {RAW_DIR}\\<TICKER>\\10k\\")
        return
    print(f"Found {len(files)} filings.")

    print(f"Loading embedding model {MODEL_NAME} (first run downloads it)...")
    model = SentenceTransformer(MODEL_NAME)

    seen = set()
    total_count = 0
    for n, path in enumerate(files, 1):
        ticker = path.parents[1].name.upper()
        print(f"\n[{n}/{len(files)}] {ticker} - {path.name}")
        html = path.read_text(encoding="utf-8", errors="ignore")
        text = html_to_text(html)

        fy = get_fiscal_year(text, path)
        if fy is None:
            print("  [skip] could not determine fiscal year")
            continue
        if (ticker, fy) in seen:
            print(f"  [warn] {ticker} FY{fy} appeared twice; later file overwrites the earlier one")
        seen.add((ticker, fy))
        print(f"  fiscal year: {fy} | text: {len(text):,} chars")

        for sec in SECTIONS:
            body = extract_section(text, sec)
            if not body:
                print(f"  Item {sec}: NOT FOUND")
                continue
            chunks = chunk_text(body)
            embeddings = model.encode(
                chunks, batch_size=BATCH_SIZE, normalize_embeddings=True
            ).tolist()
            ids = [f"{ticker}_{fy}_{sec}_{i}" for i in range(len(chunks))]
            metas = [
                {"ticker": ticker, "fiscal_year": fy, "section": sec, "chunk_index": i}
                for i in range(len(chunks))
            ]
            total_count = upsert_in_subprocess({
                "chroma_dir": str(CHROMA_DIR),
                "collection": COLLECTION,
                "ticker": ticker,
                "fiscal_year": fy,
                "section": sec,
                "ids": ids,
                "documents": chunks,
                "embeddings": embeddings,
                "metadatas": metas,
            })
            print(f"  Item {sec}: {len(body):,} chars -> {len(chunks)} chunks stored")

    print(f"\nDone. Collection '{COLLECTION}' now has {total_count:,} chunks.")


if __name__ == "__main__":
    main()