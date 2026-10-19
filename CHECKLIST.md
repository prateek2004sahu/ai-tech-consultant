# Completion checklist (code scaffolding done = what exists; you still must run, measure, write, record)
Legend: [x] implemented in this repo and covered by tests · [ ] you must do/verify yourself

## Task 1
- [x] Sitemap crawler + resumable manifest ingestion (tested offline)  - [ ] full crawl of the real site
- [x] Article parsing + image understanding code  - [ ] verify on real screenshots with your vision model
- [x] Chunking, embeddings, hybrid retrieval  - [ ] tune MIN_SCORE on real data
- [x] Grounded answers + citations + abstain
- [x] Daily incremental updates + deletion handling (scheduler + tests)
- [x] API docs (API.md, /docs) + human escalation loop
## Task 2
- [x] 50 emails with expected labels - [ ] review/extend them yourself (you must be able to explain each)
- [x] Classification + KB integration  - [x] Structured drafts  - [x] Human review + feedback history
- [x] 20-consecutive-approval logic, audit, auto-disable (unit tested)
## Task 3
- [ ] Record 3 REAL role-played meetings (samples included are placeholders you should replace)
- [x] Structured requirements + quote verification  - [x] Feasibility via Task 1 API  - [x] Scope/estimate/proposal
- [x] Follow-up diff vs approved baseline + human approval gate
## Submission
- [ ] 20+ eval cases per task RUN with real models  - [ ] 2 model comparison with cost/latency
- [ ] Rewrite DESIGN.md, fill EVALS.md, write AI_LOG.md from your real chats  - [x] One-command startup (run.sh)
- [ ] Demo video with a failure case  - [ ] Commits spread over 4 days  - [ ] No secrets committed (.env is git-ignored)
