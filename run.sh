#!/usr/bin/env bash
# One command:  ./run.sh            -> setup + start all three services
#               ./run.sh test       -> run all tests (offline, mock model)
#               ./run.sh ingest 20  -> crawl the first N help-center pages (do this before real use)
#               ./run.sh eval       -> run the three evaluation harnesses (uses your real model from .env)
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || { cp .env.example .env; echo ">> Created .env - open it, paste ONE API key, then run ./run.sh again."; [ "${LLM_PROVIDER:-}" = mock ] || exit 0; }
set -a; source .env; set +a

setup_py() {  # $1 = task dir
  [ -d "$1/.venv" ] || python3 -m venv "$1/.venv"
  "$1/.venv/bin/pip" install -q -r "$1/requirements.txt"
}
setup_py task1-knowledge-brain
setup_py task3-meeting-to-scope
[ -d task2-inbox-agent/node_modules ] || (cd task2-inbox-agent && npm install --silent)

case "${1:-start}" in
  test)
    export LLM_PROVIDER=mock EMBED_PROVIDER=mock   # tests are offline and free
    (cd task1-knowledge-brain && .venv/bin/python -m pytest -q tests)
    (cd task3-meeting-to-scope && .venv/bin/python -m pytest -q tests)
    (cd task2-inbox-agent && npm run -s typecheck && npm test --silent)
    ;;
  ingest)
    curl -s -X POST localhost:8001/ingestion/run -H 'content-type: application/json' -d "{\"limit\": ${2:-20}}"; echo
    echo "Watch progress: curl -s localhost:8001/ingestion/status"
    ;;
  eval)
    (cd task1-knowledge-brain && .venv/bin/python -m evaluation.run_eval)
    (cd task2-inbox-agent && npm run -s eval)
    (cd task3-meeting-to-scope && .venv/bin/python -m evaluation.run_eval)
    ;;
  start)
    pids=()
    trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT INT TERM
    (cd task1-knowledge-brain && exec .venv/bin/uvicorn app.main:app --port 8001) & pids+=($!)
    for i in $(seq 1 30); do curl -sf localhost:8001/health >/dev/null && break; sleep 1; done
    (cd task2-inbox-agent && exec npm start --silent) & pids+=($!)
    (cd task3-meeting-to-scope && exec .venv/bin/uvicorn app.main:app --port 8003) & pids+=($!)
    echo
    echo "  Task 1 Knowledge Brain : http://localhost:8001   (API docs: /docs)"
    echo "  Task 2 Inbox Agent     : http://localhost:8002"
    echo "  Task 3 Meeting->Scope  : http://localhost:8003"
    echo "  First time? run:  ./run.sh ingest 20   (in another terminal)"
    wait
    ;;
  *) echo "usage: ./run.sh [start|test|ingest N|eval]"; exit 1 ;;
esac
