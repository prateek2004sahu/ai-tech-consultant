# Setup A to Z (copy-paste)

1. Install Python 3.11+ and Node 20+ (`python3 --version`, `node --version`).
2. Unzip, then: `cd ai-tech-consultant`
3. Get a free Gemini key: https://aistudio.google.com/apikey (OpenAI also works).
4. `./run.sh` -> it creates `.env` and stops. Open `.env`, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...`.
5. `./run.sh` again -> installs everything, starts 3 services (8001, 8002, 8003).
6. New terminal: `./run.sh ingest 20` -> crawls 20 pages. Check: `curl -s localhost:8001/ingestion/status`.
   Open http://localhost:8001 and ask: "How do I change my logo?". Then run the full crawl: `./run.sh ingest 100000`.
7. Inbox: http://localhost:8002 -> "+ New email" -> Process -> edit/send. Bulk-load test emails from `task2-inbox-agent/data/emails.json`.
8. Scope: http://localhost:8003 -> pick sample "meeting_a_website" -> Analyse -> Approve -> load "meeting_c_followup" -> see the Changes tab.
9. Tests: `./run.sh test`. Evals: `./run.sh eval` (twice, with different `LLM_MODEL`, to compare models).
10. Windows: use WSL or Git Bash for `run.sh`.

Final Claude run (the brief wants Claude at the centre): set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`, `EMBED_PROVIDER=gemini`.
Needs paid Anthropic credits; develop on Gemini, then do the Claude comparison runs at the end.
