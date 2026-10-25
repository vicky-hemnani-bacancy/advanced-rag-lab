"""python evaluate.py [--mode advanced|naive|both] [--docs gpo,gep,imac] [--ids gpo-1,...] [--no-llm]

Metrics per question: retrieval hit@k, rank of first correct page, answer correctness (regex groups),
wrong-section leakage (must_not), abstention correctness on out-of-scope questions, ungrounded numbers, latency.
Results are saved after every question (eval/results_<mode>.json) so a network blip never loses a run.
"""
import re, json, time, argparse, statistics
from eval.questions import Q
from rag.retrieve import Retriever
from rag.answer import answer, ABSTAIN
from rag.common import ROOT

OUT = ROOT / "eval"


def page_ok(q, page):
    if "pages" in q:
        return page in q["pages"]
    if "page_range" in q:
        return q["page_range"][0] <= page <= q["page_range"][1]
    return False


def judge(q, text):
    t = text.replace("‑", "-").replace("–", "-").replace(" ", " ")
    leak = [p for p in q.get("must_not", []) if re.search(p, t, re.I)]
    return all(re.search(g, t, re.I) for g in q.get("must", [])) and not leak, leak


def evaluate_one(q, retriever, mode, k, use_llm):
    t0 = time.time()
    if use_llm:
        a = answer(q["q"], retriever, q["doc"], k=k)
        hits, text, timings, routing = a.hits, a.answer, a.timings, a.analysis.get("explain", "")
        abstained = a.abstained or ABSTAIN[:25].lower() in a.answer.lower()
        ungrounded, cited = a.ungrounded_numbers, a.cited
    else:
        res = retriever.search(q["q"], q["doc"], k=k)
        hits, text, timings, routing, abstained, ungrounded, cited = res.hits, "", res.timings, res.analysis.get("explain", ""), False, [], []
    pages = [h.chunk.page for h in hits]
    row = dict(id=q["id"], doc=q["doc"], official=q.get("official", False), q=q["q"], mode=mode, pages=pages,
               scores=[round(h.score, 2) for h in hits], kinds=[h.chunk.kind for h in hits], answer=text,
               latency=round(time.time() - t0, 1), timings={n: round(v, 1) for n, v in timings.items()},
               ungrounded=ungrounded, cited=cited, routing=routing, model=(a.model if use_llm else ""))
    if q.get("abstain"):
        row.update(type="abstain", correct=bool(abstained) if use_llm else None, top_score=hits[0].score if hits else None)
        return row
    ranks = [i + 1 for i, p in enumerate(pages) if page_ok(q, p)]
    row.update(type="answerable", hit=bool(ranks), rank=ranks[0] if ranks else None, **{"hit@1": bool(ranks and ranks[0] == 1)})
    if use_llm:
        ok, leak = judge(q, text)
        row.update(correct=ok and not abstained, leak=leak)
    return row


def run(mode, docs, ids, use_llm=True, resume=False):
    rets = {d: Retriever([d], mode) for d in docs}
    k = 4 if mode == "naive" else 6
    prev = OUT / f"results_{mode}.json"
    rows = [r for r in json.loads(prev.read_text(encoding="utf-8")) if r.get("correct") is not None or r["type"] == "answerable"] if (resume and prev.exists()) else []
    done = {r["id"] for r in rows}
    for q in Q:
        if q["doc"] not in docs or (ids and q["id"] not in ids) or q["id"] in done:
            continue
        try:
            row = evaluate_one(q, rets[q["doc"]], mode, k, use_llm)
        except Exception as e:
            print(f"[{mode:8}] {q['id']:7} ERROR {type(e).__name__}: {str(e)[:140]}", flush=True)
            continue
        rows.append(row)
        OUT.mkdir(exist_ok=True)
        (OUT / f"results_{mode}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        flag = "OK" if row.get("correct") else ("hit" if row.get("hit") else "MISS")
        if row["type"] == "abstain":
            flag = "OK" if row["correct"] else "WRONG(answered)"
        line = f"[{mode:8}] {q['id']:7} {flag:5} rank={row.get('rank')} pages={row['pages']} {row['latency']}s"
        if row["ungrounded"]:
            line += f"  ungrounded={row['ungrounded']}"
        print(line, flush=True)
        if use_llm and flag not in ("OK",):
            print(f"            -> {row['answer'][:260]!r}", flush=True)
    return rows


def summarize(rows):
    ans = [r for r in rows if r["type"] == "answerable"]
    ab = [r for r in rows if r["type"] == "abstain"]
    out = {"n": len(ans), "retrieval_hit": sum(r["hit"] for r in ans) / max(1, len(ans)),
           "hit@1": sum(r["hit@1"] for r in ans) / max(1, len(ans)),
           "mrr": sum((1 / r["rank"]) if r["rank"] else 0 for r in ans) / max(1, len(ans))}
    if ans and ans[0].get("correct") is not None:
        out["answer_correct"] = sum(bool(r["correct"]) for r in ans) / len(ans)
        out["leakage"] = sum(bool(r.get("leak")) for r in ans)
        out["answers_with_unverified_numbers"] = sum(bool(r["ungrounded"]) for r in ans)
    if ab and ab[0].get("correct") is not None:
        out["abstain_correct"] = sum(bool(r["correct"]) for r in ab) / len(ab)
    out["latency_median_s"] = statistics.median([r["latency"] for r in rows]) if rows else 0
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both")
    ap.add_argument("--docs", default="gpo,gep,imac")
    ap.add_argument("--ids", default="")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--resume", action="store_true", help="keep finished questions, run only the missing ones")
    a = ap.parse_args()
    docs, ids = a.docs.split(","), set(filter(None, a.ids.split(",")))
    modes = ["naive", "advanced"] if a.mode == "both" else [a.mode]
    allrows = {m: run(m, docs, ids, not a.no_llm, a.resume) for m in modes}
    print("\n=== SUMMARY ===")
    for m in modes:
        for scope in ["all"] + docs:
            rs = [r for r in allrows[m] if scope == "all" or r["doc"] == scope]
            if rs:
                print(f"{m:9} {scope:5}", json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in summarize(rs).items()}))
