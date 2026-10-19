/** npm run eval -- [--split test|dev|all] [--full]   Appends rows to evaluation/results.csv */
import "dotenv/config";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { classifyEmail, processEmail } from "./pipeline.js";
import { costUsd, modelName, usage } from "./llm.js";
import { Store } from "./store.js";
import type { Category } from "./types.js";

interface Item { id: string; subject: string; body: string; expected_category: Category; split: "dev" | "test" }
const args = process.argv.slice(2);
const split = args.includes("--split") ? args[args.indexOf("--split") + 1] : "all";
const full = args.includes("--full");
const items = (JSON.parse(readFileSync("data/emails.json", "utf8")) as Item[]).filter((i) => split === "all" || i.split === split);
const store = new Store(null);
mkdirSync("evaluation", { recursive: true });
const out = "evaluation/results.csv";
if (!existsSync(out)) appendFileSync(out, "task,case_id,model,mode,expected,actual,passed,latency_ms,cost_usd,failure_reason\n");
let pass = 0; const lat: number[] = []; let cost = 0;
for (const it of items) {
  const t0 = Date.now(); const u0 = { ...usage }; let actual = "error"; let why = "";
  try {
    const email = { from: "customer@example.com", subject: it.subject, body: it.body };
    actual = full ? (await processEmail(store, email, async () => ({ ok: false, error: "eval: kb skipped" }))).category : (await classifyEmail(store, email)).category;
  } catch (e) { why = (e instanceof Error ? e.message : String(e)).replace(/[,\n]/g, " ").slice(0, 100); }
  const ok = actual === it.expected_category; pass += ok ? 1 : 0;
  const ms = Date.now() - t0; lat.push(ms);
  const c = costUsd(usage.in - u0.in, usage.out - u0.out); cost += c;
  appendFileSync(out, `inbox,${it.id},${modelName()},classify,${it.expected_category},${actual},${ok ? 1 : 0},${ms},${c.toFixed(6)},${ok ? "" : why || "misclassified"}\n`);
}
lat.sort((a, b) => a - b);
console.log(`${pass}/${items.length} correct | median ${lat[Math.floor(lat.length / 2)]} ms | cost $${cost.toFixed(4)} | model ${modelName()}`);
