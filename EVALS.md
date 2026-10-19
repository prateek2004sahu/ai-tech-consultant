# EVALS (fill ONLY with numbers from your real runs; 2-3 pages)

How to produce the numbers:
1. `LLM_MODEL=<model A> ./run.sh eval` then `LLM_MODEL=<model B> ./run.sh eval` (set `PRICE_IN_PER_M`/`PRICE_OUT_PER_M` for cost).
2. Rows land in `task*/evaluation/results.csv` (task, case, model, expected, actual, passed, latency_ms, cost_usd, failure_reason).
3. Review failures by hand. Keep them in the CSV; explain each below.
4. For each model decision, run 20-30 cases per candidate (add cases to the cases files; Task 2 has 50 emails, 12 held out as `split: test`).

## Dataset
Task 1: 20 questions (`task1.../evaluation/cases.json`; fill `expect_url_contains` after inspecting your crawl; escalated questions are appended automatically).
Task 2: 50 emails (`task2.../data/emails.json`), expected category per email. Task 3: 20 cases in `task3.../evaluation/run_eval.py`.

## Results (PENDING: not yet run)
| Task | Model | Cases | Passed | Quality % | Median latency | p95 latency | Cost / case | Failures |
|---|---|---|---|---|---|---|---|---|
| 1 Knowledge | PENDING | 20 | | | | | | |
| 2 Inbox | PENDING | 50 | | | | | | |
| 3 Scope | PENDING | 20 | | | | | | |

## Model comparison and decision
PENDING (two models minimum, same cases, same prompts).

## Failure analysis
PENDING (list each failed case, cause, fix, re-run result).

## Prompt change log
| Prompt | v-old -> v-new | Problem fixed | Quality before -> after | Regressions |
|---|---|---|---|---|

## Not yet measured (be honest)
Estimate error vs a human reference, citation correctness (needs `expect_url_contains`), retrieval-mode comparison.
