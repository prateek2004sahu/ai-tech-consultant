# AI Tech Consultant

One shared **Knowledge Brain** (Python/FastAPI, RAG over a help center, images included) used by two apps:
an **Inbox Agent** (TypeScript, drafts replies, human approves, learns from edits) and **Meeting to Scope**
(Python, transcript -> scope, estimate, proposal, change report). Tasks 2 and 3 call Task 1 **only over HTTP**.

## Prerequisites
Python 3.11+, Node 20+, one API key (free Gemini key works: https://aistudio.google.com/apikey).

## Run
```bash
./run.sh              # 1st run creates .env -> paste ONE key -> run again
./run.sh ingest 20    # crawl first 20 help-center pages (then drop the number for the full crawl)
./run.sh test         # tests (offline)
./run.sh eval         # evals with your real model; results -> */evaluation/results.csv
```
Open: Knowledge Brain http://localhost:8001 · Inbox http://localhost:8002 · Scope http://localhost:8003

## Config (`.env`)
`LLM_PROVIDER` (gemini | openai | anthropic), the matching `*_API_KEY`, `LLM_MODEL` to switch models, `KB_URL`.
Use `LLM_PROVIDER=anthropic` (+ `EMBED_PROVIDER=gemini`) for the Claude-centred final run the brief requires.

## Simulated / not done
Email sending and client delivery are simulated. Fill in `EVALS.md` from your real runs. See `DESIGN.md` for limits.
