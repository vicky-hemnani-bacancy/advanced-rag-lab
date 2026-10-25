"""FastAPI service for the RAG app.   Run:  .venv\\Scripts\\python run_server.py   (API on :8100)

If the React app has been built (rag-ui/dist) it is served at "/"; otherwise the plain HTML page in ui/ is used.
For development run the React dev server (npm run dev, :5173); CORS allows it.
"""
from __future__ import annotations
import functools
import pymupdf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rag.common import DOCS, PDF_DIR, ROOT
from rag.retrieve import Retriever
from rag.answer import answer
from rag import llm
from rag.llm import LLMUnavailable
from eval.questions import Q

app = FastAPI(title="Advanced RAG over 3 document types")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class Ask(BaseModel):
    question: str
    doc: str = "auto"               # auto | gpo | gep | imac
    mode: str = "advanced"          # advanced | naive
    k: int = 6
    model: str | None = None        # one of /api/models, default = server default


@functools.lru_cache(maxsize=8)
def retriever(mode: str, doc: str) -> Retriever:
    return Retriever(list(DOCS) if doc == "auto" else [doc], mode)


@app.get("/api/health")
def health():
    return {"ok": True, "provider": llm.PROVIDER, "default_model": llm.LLM_MODEL}


@app.get("/api/models")
def models():
    return {"provider": llm.PROVIDER, "default": llm.LLM_MODEL, "models": llm.available_models()}


@app.get("/api/docs")
def docs():
    out = []
    for k, d in DOCS.items():
        n = len(pymupdf.open(PDF_DIR / d["file"]))
        out.append({"key": k, "title": d["title"], "desc": d["desc"], "pages": n,
                    "samples": [q["q"] for q in Q if q["doc"] == k and not q.get("abstain")][:6]})
    return out


@app.post("/api/ask")
def ask(body: Ask):
    if body.doc != "auto" and body.doc not in DOCS:
        raise HTTPException(404, "unknown document")
    if body.mode not in ("advanced", "naive"):
        raise HTTPException(400, "mode must be advanced or naive")
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    if body.model and body.model not in llm.available_models():
        raise HTTPException(400, f"unknown model; choose one of {llm.available_models()}")
    r = retriever(body.mode, body.doc)
    try:
        a = answer(body.question, r, None if body.doc == "auto" else body.doc, k=4 if body.mode == "naive" else body.k,
                   model=body.model, max_wait=45)
    except LLMUnavailable as e:
        raise HTTPException(503, str(e))
    return {"answer": a.answer, "abstained": a.abstained, "cited": a.cited, "ungrounded_numbers": a.ungrounded_numbers,
            "routing": a.analysis.get("explain", ""), "timings": {k: round(v, 2) for k, v in a.timings.items()},
            "sources": a.sources(), "mode": body.mode, "model": a.model}


@functools.lru_cache(maxsize=128)
def _render(doc: str, page: int, dpi: int) -> bytes:
    d = pymupdf.open(PDF_DIR / DOCS[doc]["file"])
    return d[page - 1].get_pixmap(dpi=dpi).tobytes("png")


@app.get("/api/page/{doc}/{page}")
def page_image(doc: str, page: int, dpi: int = 90):
    if doc not in DOCS:
        raise HTTPException(404)
    try:
        return Response(_render(doc, page, min(dpi, 160)), media_type="image/png")
    except IndexError:
        raise HTTPException(404, "page out of range")


_DIST = ROOT / "rag-ui" / "dist"
if _DIST.exists():                                          # built React app
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="react")
else:                                                       # fallback: plain HTML page
    @app.get("/")
    def index():
        return FileResponse(ROOT / "ui" / "index.html")

    app.mount("/ui", StaticFiles(directory=ROOT / "ui"), name="ui")
