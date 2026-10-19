# DESIGN (draft: rewrite the "why" parts in YOUR words; 3-5 pages max)

## 1. The problem
(Your words: small software firms drown in repeated support questions, slow replies, and slow proposals. Cheap AI code
means the slow part is everything around code.)

## 2. Architecture (matches the code)
```
 Help center sitemap -> [Task 1 Knowledge Brain: crawl -> parse -> images(vision) -> chunks -> embeddings -> SQLite]
                                   ^  FastAPI  /query  /ingestion/*  /escalations/*
                  HTTP (typed client, timeouts, retries, request id)
        +--------------------------+--------------------------+
 [Task 2 Inbox Agent (TS)]                          [Task 3 Meeting to Scope (Py)]
 classify -> KB -> draft -> checks -> human         analyst -> feasibility(KB) -> scope -> estimate -> proposal -> human
 -> feedback store -> autonomy rule                 follow-up diff vs APPROVED baseline
```
Why one shared service: one place to keep knowledge fresh; both apps improve when an expert answers an escalation; any
business can plug in its own help center by changing `SITEMAP_URL`.

## 3. Key design choices (and why)
- **SQLite + numpy vectors** (Task 1): zero setup, fine for a few thousand chunks. Swap to pgvector above ~100k chunks.
- **Hybrid retrieval** (0.7 vector + 0.3 keyword) with `mode` switch so you can measure vector vs keyword vs hybrid.
- **Polite crawling**: global delay, small concurrency, backoff, robots.txt, per-page checkpoint in the manifest, idempotent chunk replace.
- **Images are first-class**: each screenshot gets a vision description stored as its own chunk linked to the article; uncertain text must say "unclear".
- **Abstain, then escalate**: weak evidence or a model "insufficient" -> `needs_human` + expert task; approved expert answers become searchable and join the eval set.
- **`top_score` is not called confidence**: it is not calibrated, so the API says so.
- **Task 2 autonomy**: "same kind" = same category; "unchanged" = identical after trimming/lowercasing/whitespace collapse (comparison on text, not the button clicked).
  Reaching 20 only makes a category *eligible*; a human must enable it; refunds, complaints, quotes, project requests never go automatic;
  every 5th auto-send is audited; any edit/bad audit disables it and resets the streak. Prompts are versioned with rollback.
- **Task 3 agents (5, one job each)**: analyst, feasibility, scope, estimator, proposal+review. Quotes are verified against the transcript;
  unclear or unverified items are listed but **not priced**; "no KB evidence" means *needs clarification*, never "custom work".
  Follow-ups are diffed against the last **approved** version; unapproved drafts cannot be a baseline or be sent.
- **Provider-agnostic LLM layer**: one small module, Gemini/OpenAI/Anthropic, so model comparisons are a one-line env change.

## 4. What I dropped (and why)  -> edit with your real decisions
Real email (IMAP/SMTP), auth/users, Postgres, knowledge graph, automatic prompt rewriting (feedback is surfaced in `/api/stats`; a human writes the new prompt version).

## 5. Models  -> fill from EVALS.md
(Your chosen model per task and the numbers that justify it.)

## 6. What breaks / limits  -> keep this honest
- Hash-embedding mock mode is for tests only. Cosine thresholds (`MIN_SCORE`) must be tuned on your data.
- JSON file stores in Tasks 2/3 are not concurrency-safe across processes.
- Estimates are LLM estimates, not validated against actuals until you add reference estimates.
- Screenshots behind login or lazy-loaded by JavaScript are not fetched (static HTML parser).

## 7. Next steps
Reranking, calibrated confidence, real mailbox integration, pgvector, estimate calibration from past projects.
