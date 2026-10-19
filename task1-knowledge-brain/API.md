# Knowledge Brain API (interactive docs: http://localhost:8001/docs)

Auth: if `KB_API_KEY` is set, send header `X-API-Key`. Optional `X-Request-ID` is echoed back.

| Endpoint | Purpose |
|---|---|
| `POST /query` | Answer a question from evidence |
| `POST /ingestion/run` | `{ "limit": 20, "force": false }` start incremental ingestion (202) |
| `GET /ingestion/status` | last run (added/updated/removed/failed) + page and chunk counts |
| `POST /escalations` / `GET /escalations?status=open` | create / list expert tasks |
| `POST /escalations/{id}/resolve` | `{ "answer": "...", "approved": true }` approved answers become searchable |
| `GET /health` | liveness + active chunk count |

## POST /query
Request: `{ "question": "How do I change my logo?", "top_k": 6, "mode": "hybrid", "escalate": true, "context": null }`

Response:
```json
{
  "answer": "Open Design Settings...",
  "status": "answered",                    // or "insufficient_evidence"
  "sources": [{"title": "...", "url": "https://...", "relevance": 0.71}],
  "images": ["https://.../screenshot.png"], // screenshots that supported the answer
  "top_score": 0.71,                        // best retrieval score; NOT a calibrated probability
  "needs_human": false,                     // true when insufficient_evidence
  "escalation_id": null,                    // task id when escalated
  "prompt_version": "answer-v1"
}
```
Errors: 401 bad key, 422 invalid body, 503 model unavailable, 504 timeout. Clients must treat any non-200 as "knowledge unavailable" and never invent an answer.
