"""FastAPI backend for MarketLens RAG application."""
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ask import LLM_MODEL, ask_structured

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = next(
    (
        path
        for path in [
            ROOT / "web",
            SRC_DIR / "web",
            ROOT / "marketlens" / "web",
        ]
        if (path / "index.html").exists()
    ),
    ROOT / "web",
)

app = FastAPI(title="MarketLens 10-K RAG API", version="1.0.0")

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class AskRequest(BaseModel):
    question: str
    ticker: Optional[str] = None
    year: Optional[int] = None
    section: Optional[str] = None
    top_k: int = 5
    model: str = LLM_MODEL


@app.get("/")
def serve_frontend():
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "MarketLens API is running. Visit /docs for interactive API docs."}


@app.get("/health")
def health_check():
    return {"status": "ok", "model": LLM_MODEL}


@app.post("/api/ask")
def api_ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        return ask_structured(
            question=req.question.strip(),
            ticker=req.ticker.strip() if req.ticker else None,
            year=req.year,
            section=req.section.strip() if req.section else None,
            top_k=req.top_k,
            model=req.model,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))