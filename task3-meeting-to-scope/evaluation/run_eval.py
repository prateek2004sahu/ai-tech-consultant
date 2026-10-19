"""python -m evaluation.run_eval [--out evaluation/results.csv]
20 cases: 14 requirement-extraction + 6 change-detection against a fixed baseline.
Pass = every expected keyword appears in the extracted requirement text (extraction) or the right change type is reported (change).
Add your own cases and a human-reviewed estimate reference to measure estimate error (see EVALS.md).
"""
import argparse, asyncio, csv, os, time
from dotenv import load_dotenv
load_dotenv()
from app import agents, llm  # noqa: E402
from app.diff import apply_changes  # noqa: E402
from app.models import Requirement  # noqa: E402

EXTRACT = [  # (id, client lines, expected keywords)  -- realistic client phrasing, vague on purpose
 ("SC-01", "We want customers to filter products by size and colour.", ["filter", "size"]),
 ("SC-02", "Our checkout is too long. We need it shorter.", ["checkout"]),
 ("SC-03", "We need an order confirmation email sent to every customer.", ["confirmation", "email"]),
 ("SC-04", "Please add a wishlist so people can save products.", ["wishlist"]),
 ("SC-05", "We want to accept payments through PayPal.", ["paypal"]),
 ("SC-06", "The site must be available in Spanish as well.", ["spanish"]),
 ("SC-07", "Customers should be able to track their orders online.", ["track", "order"]),
 ("SC-08", "We need a monthly sales report sent to our accountant.", ["report", "monthly"]),
 ("SC-09", "I would like a live chat widget on the contact page.", ["chat"]),
 ("SC-10", "Our staff want an alert when stock is low.", ["stock"]),
 ("SC-11", "We need the product pages to load faster.", ["product", "faster"]),
 ("SC-12", "Add a newsletter signup form in the footer.", ["newsletter"]),
 ("SC-13", "We want discount codes at checkout.", ["discount"]),
 ("SC-14", "We need two-factor login for our admin users.", ["login"]),
]
BASE = [("REQ-001", "Filter products by category and price"), ("REQ-002", "Brand filter on search"), ("REQ-003", "Mobile menu easier to use")]
CHANGE = [  # (id, client line, expected change key)
 ("SC-15", "We do not need the brand filter anymore, please drop it.", "removed"),
 ("SC-16", "We also want customers to save favourite products to a wishlist.", "added"),
 ("SC-17", "The mobile menu should now include a sticky search bar, not just an easier menu.", "modified"),
 ("SC-18", "Customers should also be able to sort results by rating.", "added"),
 ("SC-19", "We do not need the filter by category and price anymore, please drop it.", "removed"),
 ("SC-20", "Thanks for the update, everything looks good to us.", "none"),
]


async def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="evaluation/results.csv"); a = ap.parse_args()
    rows = []
    def rec(cid, expected, actual, ok, t0, u0, why=""):
        u1 = llm.usage_snapshot()
        rows.append({"task": "scope", "case_id": cid, "model": f"{llm.provider()}:{llm.chat_model()}", "expected": expected, "actual": actual,
                     "passed": int(ok), "latency_ms": int((time.time() - t0) * 1000),
                     "cost_usd": round(llm.cost_usd(u1["in"] - u0["in"], u1["out"] - u0["out"]), 6), "failure_reason": "" if ok else (why or "mismatch")})
    for cid, line, kws in EXTRACT:
        t0, u0 = time.time(), llm.usage_snapshot()
        try:
            ex = await agents.analyse_chunk(f"L1: Client: {line}", [])
            text = " ".join(r.description.lower() for r in ex.requirements)
            rec(cid, ",".join(kws), text[:80], bool(ex.requirements) and all(k in text for k in kws), t0, u0)
        except Exception as e:
            rec(cid, ",".join(kws), "error", False, t0, u0, str(e)[:100].replace(",", ";"))
    base = [Requirement(id=i, description=d, status="confirmed") for i, d in BASE]
    for cid, line, want in CHANGE:
        t0, u0 = time.time(), llm.usage_snapshot()
        try:
            ex = await agents.analyse_chunk(f"L1: Client: {line}", base)
            _, _, rep = apply_changes(base, [], ex, "M2", lambda e: Requirement(description=e.description))
            got = next((k for k in ("removed", "modified", "added") if rep[k]), "none")
            rec(cid, want, got, got == want, t0, u0)
        except Exception as e:
            rec(cid, want, "error", False, t0, u0, str(e)[:100].replace(",", ";"))
    new = not os.path.exists(a.out)
    with open(a.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        if new: w.writeheader()
        w.writerows(rows)
    lat = sorted(r["latency_ms"] for r in rows)
    print(f"{sum(r['passed'] for r in rows)}/{len(rows)} passed | median {lat[len(lat)//2]} ms | cost ${sum(r['cost_usd'] for r in rows):.4f}")

asyncio.run(main())
