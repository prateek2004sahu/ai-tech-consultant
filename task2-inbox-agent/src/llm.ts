/** Provider-agnostic LLM client (plain fetch). LLM_PROVIDER: gemini | openai | anthropic | mock */
export type Task = "classify" | "draft";
type MockFn = (user: string) => string;
const mocks: Partial<Record<Task, MockFn>> = {};
export const registerMock = (t: Task, f: MockFn): void => { mocks[t] = f; };

export const usage = { in: 0, out: 0, calls: 0 };
const provider = (): string => (process.env.LLM_PROVIDER ?? "mock").toLowerCase();
const DEFAULTS: Record<string, string> = {
  gemini: "gemini-2.5-flash", openai: "gpt-4o-mini", anthropic: "claude-haiku-5-5", mock: "mock",
};
export const modelName = (): string => process.env.LLM_MODEL ?? DEFAULTS[provider()] ?? "unknown";
export const costUsd = (din: number, dout: number): number =>
  (din * Number(process.env.PRICE_IN_PER_M ?? 0) + dout * Number(process.env.PRICE_OUT_PER_M ?? 0)) / 1e6;

async function post(url: string, headers: Record<string, string>, body: unknown): Promise<any> {
  let last = "";
  for (let i = 0; i < 4; i++) {
    const r = await fetch(url, {
      method: "POST", headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body), signal: AbortSignal.timeout(60_000),
    });
    if ([429, 500, 502, 503, 529].includes(r.status)) {
      last = `HTTP ${r.status}`;
      await new Promise((res) => setTimeout(res, 2 ** i * 1000));
      continue;
    }
    if (!r.ok) throw new Error(`LLM HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
    return r.json();
  }
  throw new Error(`LLM failed after retries: ${last}`);
}

export async function chatJson(task: Task, system: string, user: string): Promise<string> {
  const p = provider();
  if (p === "mock") {
    const out = (mocks[task] ?? (() => "{}"))(user);
    usage.calls++; usage.in += Math.ceil((system.length + user.length) / 4); usage.out += Math.ceil(out.length / 4);
    return out;
  }
  const key = process.env[`${p.toUpperCase()}_API_KEY`];
  if (!key) throw new Error(`${p.toUpperCase()}_API_KEY is not set`);
  const model = modelName();
  let text = ""; let tin = 0; let tout = 0;
  if (p === "gemini") {
    const d = await post(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
      { "x-goog-api-key": key },
      { systemInstruction: { parts: [{ text: system }] }, contents: [{ role: "user", parts: [{ text: user }] }],
        generationConfig: { responseMimeType: "application/json", temperature: 0.2, maxOutputTokens: 2000 } });
    text = (d.candidates?.[0]?.content?.parts ?? []).map((x: { text?: string }) => x.text ?? "").join("");
    tin = d.usageMetadata?.promptTokenCount ?? 0; tout = d.usageMetadata?.candidatesTokenCount ?? 0;
  } else if (p === "openai") {
    const d = await post("https://api.openai.com/v1/chat/completions", { authorization: `Bearer ${key}` },
      { model, temperature: 0.2, response_format: { type: "json_object" },
        messages: [{ role: "system", content: system }, { role: "user", content: user }] });
    text = d.choices?.[0]?.message?.content ?? "";
    tin = d.usage?.prompt_tokens ?? 0; tout = d.usage?.completion_tokens ?? 0;
  } else if (p === "anthropic") {
    const d = await post("https://api.anthropic.com/v1/messages",
      { "x-api-key": key, "anthropic-version": "2023-06-01" },
      { model, max_tokens: 2000, system, messages: [{ role: "user", content: `${user}\n\nReturn ONLY valid JSON.` }] });
    text = (d.content ?? []).filter((x: { type: string }) => x.type === "text").map((x: { text: string }) => x.text).join("");
    tin = d.usage?.input_tokens ?? 0; tout = d.usage?.output_tokens ?? 0;
  } else throw new Error(`Unknown LLM_PROVIDER ${p}`);
  usage.calls++; usage.in += tin; usage.out += tout;
  return text;
}

export function extractJson(text: string): unknown {
  const t = text.replace(/^```(?:json)?|```$/gm, "").trim();
  try { return JSON.parse(t); } catch {
    const m = t.match(/\{[\s\S]*\}/);
    if (!m) throw new Error("no JSON in model output");
    return JSON.parse(m[0]);
  }
}
