"""Run: python -m evaluation.run_eval [--mode hybrid|vector|keyword] [--out evaluation/results.csv]

Fill `expect_url_contains` in cases.json after you inspect your crawled data to also score citation correctness.
Appends one row per case: model, quality (pass), latency, cost, failure reason. Failed cases are kept.
"""
import argparse, asyncio, csv, json, os, time
from dotenv import load_dotenv
load_dotenv()
from app import llm, rag  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="hybrid")
    ap.add_argument("--out", default="evaluation/results.csv")
    a = ap.parse_args()
    cases = json.load(open("evaluation/cases.json"))
    if os.path.exists("evaluation/escalated_cases.jsonl"):
        cases += [dict(json.loads(l), id=f"ESC-{i}") for i, l in enumerate(open("evaluation/escalated_cases.jsonl"))]
    new = not os.path.exists(a.out)
    rows = []
    for c in cases:
        u0, t0 = llm.usage_snapshot(), time.time()
        try:
            r = await rag.answer(c["question"], mode=a.mode, escalate=False)
            err = ""
        except Exception as e:
            r, err = {"status": "error", "sources": []}, str(e)[:120]
        u1 = llm.usage_snapshot()
        got = "answer" if r["status"] == "answered" else "abstain"
        ok = got == c["expect"] and not err
        if ok and c.get("expect_url_contains"):
            ok = any(c["expect_url_contains"] in s["url"] for s in r["sources"])
        rows.append({"task": "knowledge", "case_id": c["id"], "model": f"{llm.provider()}:{llm.chat_model()}",
                     "retrieval_mode": a.mode, "expected": c["expect"], "actual": got, "passed": int(ok),
                     "latency_ms": int((time.time() - t0) * 1000),
                     "cost_usd": round(llm.cost_usd(u1["in"] - u0["in"], u1["out"] - u0["out"]), 6),
                     "failure_reason": err or ("" if ok else f"expected {c['expect']} got {got}")})
    with open(a.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new: w.writeheader()
        w.writerows(rows)
    p = sum(r["passed"] for r in rows)
    lat = sorted(r["latency_ms"] for r in rows)
    print(f"{p}/{len(rows)} passed | median {lat[len(lat)//2]} ms | p95 {lat[int(len(lat)*.95)-1]} ms | cost ${sum(r['cost_usd'] for r in rows):.4f}")

asyncio.run(main())
