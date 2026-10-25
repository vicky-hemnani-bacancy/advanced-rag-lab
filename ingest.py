"""CLI: python ingest.py gpo|gep|imac|all [--naive]"""
import sys, time
from rag.common import DOCS
from rag.store import build_index


def run(doc: str, naive: bool):
    t = time.time()
    if naive:
        from rag.ingest_narrative import ingest_naive
        chunks, name = ingest_naive(doc), f"naive_{doc}"
    elif doc == "gpo":
        from rag.ingest_narrative import ingest
        chunks, name = ingest("gpo"), "gpo"
    elif doc == "gep":
        from rag.ingest_structured import ingest
        chunks, name = ingest("gep"), "gep"
    else:
        from rag.ingest_visual import ingest
        chunks, name = ingest("imac"), "imac"
    print(f"[{name}] parsed {len(chunks)} chunks in {time.time()-t:.1f}s; embedding...", flush=True)
    build_index(name, chunks, progress=lambda a, b: print(f"  embedded {a}/{b}", end="\r", flush=True))
    print(f"\n[{name}] indexed {len(chunks)} chunks in {time.time()-t:.1f}s", flush=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    naive = "--naive" in sys.argv
    for d in (list(DOCS) if (not args or args[0] == "all") else args):
        run(d, naive)
