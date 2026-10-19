import "dotenv/config";
import { fileURLToPath } from "node:url";
import express, { type NextFunction, type Request, type Response } from "express";
import { z } from "zod";
import { THRESHOLD, NEVER_AUTO } from "./autonomy.js";
import { modelName } from "./llm.js";
import { auditRecord, processEmail, reviewRecord } from "./pipeline.js";
import { Store } from "./store.js";
import { CATEGORIES, EmailInSchema, type Category } from "./types.js";

export function buildApp(store: Store): express.Express {
  const app = express();
  app.use(express.json({ limit: "200kb" }));
  // fileURLToPath works on Windows (new URL(...).pathname does not)
  app.use(express.static(fileURLToPath(new URL("../public", import.meta.url))));
  const wrap = (fn: (req: Request, res: Response) => Promise<unknown> | unknown) =>
    (req: Request, res: Response, next: NextFunction): void => { Promise.resolve(fn(req, res)).catch(next); };
  const param = (req: Request, k: string): string => String(req.params[k] ?? "");

  app.get("/api/health", (_q, res) => res.json({ ok: true, model: modelName() }));

  app.post("/api/emails", wrap(async (req, res) => {
    const email = EmailInSchema.parse(req.body);
    res.status(201).json(await processEmail(store, email));
  }));
  app.get("/api/emails", (req, res) => {
    const st = req.query.status;
    res.json(store.db.records.filter((r) => !st || r.status === st));
  });
  app.post("/api/emails/:id/review", wrap((req, res) => {
    const b = z.object({ action: z.enum(["approve", "edit", "reject", "escalate"]), final_text: z.string().optional(), reason: z.string().max(500).optional() }).parse(req.body);
    res.json(reviewRecord(store, param(req, "id"), b.action, b.final_text, b.reason));
  }));
  app.post("/api/audit/:id", wrap((req, res) => {
    res.json(auditRecord(store, param(req, "id"), z.object({ ok: z.boolean() }).parse(req.body).ok));
  }));

  app.get("/api/autonomy", (_q, res) => res.json({ threshold: THRESHOLD, never_auto: [...NEVER_AUTO], state: store.db.autonomy }));
  app.post("/api/autonomy/:category/:op", wrap((req, res) => {
    const cat = z.enum(CATEGORIES).parse(param(req, "category")) as Category;
    const st = store.db.autonomy[cat];
    if (param(req, "op") === "enable") {
      if (!st.eligible || NEVER_AUTO.has(cat)) { res.status(409).json({ error: "category not eligible" }); return; }
      st.enabled = true; st.history.push(`${new Date().toISOString()} autonomy enabled by human`);
    } else { st.enabled = false; st.history.push(`${new Date().toISOString()} autonomy disabled by human`); }
    store.save(); res.json(st);
  }));

  app.get("/api/prompts", (_q, res) => res.json(store.db.prompts));
  app.post("/api/prompts/:name", wrap((req, res) => {   // new version (inactive until activated)
    const name = z.enum(["classify", "draft"]).parse(param(req, "name"));
    const b = z.object({ text: z.string().min(20), note: z.string().min(3) }).parse(req.body);
    const list = store.db.prompts[name];
    list.push({ version: Math.max(...list.map((p) => p.version)) + 1, text: b.text, note: b.note, active: false, createdAt: new Date().toISOString() });
    store.save(); res.status(201).json(list);
  }));
  app.post("/api/prompts/:name/activate", wrap((req, res) => {  // also used for rollback
    const name = z.enum(["classify", "draft"]).parse(param(req, "name"));
    const v = z.object({ version: z.number().int() }).parse(req.body).version;
    const list = store.db.prompts[name];
    if (!list.some((p) => p.version === v)) { res.status(404).json({ error: "unknown version" }); return; }
    list.forEach((p) => { p.active = p.version === v; }); store.save(); res.json(list);
  }));

  app.get("/api/stats", (_q, res) => {   // feedback summary: where do humans keep editing?
    const out: Record<string, { reviewed: number; unchanged: number; avgEditRatio: number; promptVersions: number[] }> = {};
    for (const r of store.db.records) {
      if (r.status !== "sent" && r.status !== "rejected") continue;
      const o = (out[r.category] ??= { reviewed: 0, unchanged: 0, avgEditRatio: 0, promptVersions: [] });
      o.reviewed++; o.unchanged += r.unchanged ? 1 : 0; o.avgEditRatio += r.editRatio ?? 1;
      if (!o.promptVersions.includes(r.draftPromptVersion)) o.promptVersions.push(r.draftPromptVersion);
    }
    for (const o of Object.values(out)) o.avgEditRatio = Math.round((o.avgEditRatio / o.reviewed) * 100) / 100;
    res.json(out);
  });

  app.use((err: unknown, _q: Request, res: Response, _n: NextFunction) => {
    if (err instanceof z.ZodError) { res.status(422).json({ error: "validation", issues: err.issues }); return; }
    const e = err as { status?: number; message?: string };
    res.status(e.status ?? 500).json({ error: e.message ?? "internal error" });
  });
  return app;
}

// Start the server only when this file is run directly (npm start)
if (process.argv[1]?.endsWith("server.ts")) {
  const port = Number(process.env.PORT ?? 8002);
  buildApp(new Store()).listen(port, () => console.log(`Inbox Agent on http://localhost:${port}  (model: ${modelName()})`));
}