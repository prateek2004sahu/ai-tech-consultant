import { KbResponseSchema, type KbResult } from "./types.js";

/** Typed client for Task 1. Never fabricates an answer: any failure becomes {ok:false}. */
export async function queryKnowledge(question: string, requestId: string, context?: string): Promise<KbResult> {
  const base = process.env.KB_URL ?? "http://localhost:8001";
  const headers: Record<string, string> = { "content-type": "application/json", "x-request-id": requestId };
  if (process.env.KB_API_KEY) headers["x-api-key"] = process.env.KB_API_KEY;
  let lastErr = "unknown";
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await fetch(`${base}/query`, {
        method: "POST", headers, signal: AbortSignal.timeout(Number(process.env.KB_TIMEOUT_MS ?? 30_000)),
        body: JSON.stringify({ question, context, escalate: true }),
      });
      if (r.status >= 500) { lastErr = `HTTP ${r.status}`; continue; }
      if (!r.ok) return { ok: false, error: `Knowledge API HTTP ${r.status}` };
      const parsed = KbResponseSchema.safeParse(await r.json());
      return parsed.success ? { ok: true, data: parsed.data } : { ok: false, error: "Knowledge API returned an unexpected shape" };
    } catch (e) {
      lastErr = e instanceof Error ? e.message : String(e);
    }
  }
  return { ok: false, error: `Knowledge service unavailable: ${lastErr}` };
}
