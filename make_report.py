"""Fill the RESULTS block of README.md from eval/results_{naive,advanced}.json (no hand-copied numbers)."""
import json, re
from evaluate import summarize
from eval.questions import Q
from rag.common import ROOT

START, END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def load(mode):
    p = ROOT / "eval" / f"results_{mode}.json"
    return {r["id"]: r for r in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else {}


def pct(x):
    return f"{round(100 * x)}%"


def mark(r):
    if r is None:
        return "not run"
    if r["type"] == "abstain":
        return "abstained" if r["correct"] else "answered (wrong)"
    return "correct" if r.get("correct") else ("right page, wrong answer" if r.get("hit") else "wrong page")


def build() -> str:
    naive, adv = load("naive"), load("advanced")
    out = []
    ids_done = set(naive) & set(adv)
    out.append(f"Evaluated on **{len(Q)} questions**; **{len(ids_done)}** have a result in both pipelines and are compared below.\n")
    out.append("### Summary (answerable questions)\n")
    out.append("| Scope | Pipeline | n | Right page retrieved | Right page ranked #1 | MRR | Answer correct | Median time per question* |")
    out.append("|---|---|---|---|---|---|---|---|")
    for scope in ["all", "gpo", "gep", "imac"]:
        for name, res in (("naive", naive), ("advanced", adv)):
            rows = [r for i, r in res.items() if i in ids_done and (scope == "all" or r["doc"] == scope)]
            ans = [r for r in rows if r["type"] == "answerable"]
            if not ans:
                continue
            s = summarize(rows)
            out.append(f"| {scope} | {name} | {s['n']} | {pct(s['retrieval_hit'])} | {pct(s['hit@1'])} | {s['mrr']:.2f} | "
                       f"{pct(s['answer_correct'])} | {s['latency_median_s']:.0f}s |")
    ab = [r for i, r in adv.items() if r["type"] == "abstain"]
    abn = [r for i, r in naive.items() if r["type"] == "abstain"]
    out.append(f"\nOut-of-scope questions (should answer \"not found\"): advanced {sum(bool(r['correct']) for r in ab)}/{len(ab)}, "
               f"naive {sum(bool(r['correct']) for r in abn)}/{len(abn)}.")
    leak = sum(bool(r.get('leak')) for r in adv.values())
    unv = sum(bool(r['ungrounded']) for r in adv.values())
    out.append(f"Wrong-section leakage in advanced answers: {leak}. Answers flagged with numbers not found in their sources: {unv}.\n")
    models = sorted({r.get("model") for res in (naive, adv) for r in res.values() if r.get("model")})
    out.append("\n\\* Wall-clock time per question during the batch run (retrieval, reranking and the LLM call; the naive "
               "pipeline has no reranking). Generator model: " + (", ".join(f"`{m}`" for m in models) or "not recorded") + ".\n")
    out.append("### Per question\n")
    out.append("| id | official | question | naive | advanced | note |")
    out.append("|---|---|---|---|---|---|")
    for q in Q:
        n, a = naive.get(q["id"]), adv.get(q["id"])
        out.append(f"| {q['id']} | {'yes' if q.get('official') else ''} | {q['q']} | {mark(n)} | {mark(a)} | {q.get('note', '')} |")
    return "\n".join(out)


if __name__ == "__main__":
    p = ROOT / "README.md"
    s = p.read_text(encoding="utf-8")
    block = f"{START}\n{build()}\n{END}"
    s = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda m: block, s, flags=re.S)
    p.write_text(s, encoding="utf-8")
    print("README results block updated")
