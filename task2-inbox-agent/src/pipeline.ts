import { randomUUID } from "node:crypto";
import { applyOutcome, canAutoSend, AUDIT_EVERY, editRatio as editRatioOf, isUnchanged as normalizeEq } from "./autonomy.js";
import { queryKnowledge } from "./knowledgeClient.js";
import { chatJson, extractJson, modelName, registerMock } from "./llm.js";
import type { Store } from "./store.js";
import {
  ClassificationSchema, DraftSchema, RISK, type Category, type Classification, type DraftOut,
  type EmailIn, type KbResult, type Rec,
} from "./types.js";

export type KbFn = (q: string, rid: string, ctx?: string) => Promise<KbResult>;
const wrap = (e: EmailIn): string =>
  `<email>\nFrom: ${e.from}\nSubject: ${e.subject}\n\n${e.body}\n${e.thread_context ? `\nPrevious thread:\n${e.thread_context}` : ""}</email>`;

/** Call model, validate against schema, retry once with the validation error. */
async function structured<T>(task: "classify" | "draft", system: string, user: string, parse: (x: unknown) => T): Promise<T> {
  let err = "";
  for (let i = 0; i < 2; i++) {
    try { return parse(extractJson(await chatJson(task, system, i ? `${user}\n\nYour previous output was invalid: ${err}. Return valid JSON only.` : user))); }
    catch (e) { err = e instanceof Error ? e.message.slice(0, 300) : String(e); }
  }
  throw new Error(`model output failed validation twice: ${err}`);
}

export const classifyEmail = (store: Store, email: EmailIn): Promise<Classification> =>
  structured("classify", store.activePrompt("classify").text, wrap(email), (x) => ClassificationSchema.parse(x));

const COMMIT = /([$€£₹]\s?\d)|\b(we will|we'll|i will|i'll) (refund|credit|waive|deliver|ship|complete)\b|\brefund (has been|is) (approved|issued|processed)\b|\bguarantee/i;

export async function processEmail(store: Store, email: EmailIn, kb: KbFn = queryKnowledge): Promise<Rec> {
  const id = randomUUID().slice(0, 8);
  const cls = await classifyEmail(store, email);
  const kbRes = await kb(cls.question_for_kb || email.subject, id, email.thread_context);
  const base = {
    id, email, category: cls.category, urgency: cls.urgency, risk: RISK[cls.category], summary: cls.summary, kb: kbRes,
    draftPromptVersion: store.activePrompt("draft").version, classifyPromptVersion: store.activePrompt("classify").version,
    model: modelName(), createdAt: new Date().toISOString(), qualityFlags: [] as string[],
  };
  if (!kbRes.ok) {  // never fabricate when the knowledge service is down
    const rec: Rec = { ...base, draft: null, needsHuman: true, status: "kb_unavailable" };
    store.db.records.unshift(rec); store.save(); return rec;
  }
  const knowledge = kbRes.data.status === "answered"
    ? `${kbRes.data.answer}\nSources: ${kbRes.data.sources.map((s) => s.url).join(", ")}` : "(none: knowledge base had no sufficient evidence)";
  const draft: DraftOut = await structured("draft", store.activePrompt("draft").text,
    `CATEGORY: ${cls.category}\nKNOWLEDGE:\n${knowledge}\n\n${wrap(email)}`, (x) => DraftSchema.parse(x));
  const flags: string[] = [];
  if (COMMIT.test(draft.reply)) flags.push("possible commitment (price/refund/date) in draft");
  if (draft.makes_commitment) flags.push("model flagged a commitment");
  if (kbRes.data.status !== "answered") flags.push("no grounded evidence");
  const needsHuman = draft.needs_human || RISK[cls.category] === "high" || flags.length > 0;
  let rec: Rec = { ...base, draft: draft.reply, needsHuman, qualityFlags: flags, status: "pending_review" };

  const st = store.db.autonomy[cls.category];
  const verdict = canAutoSend(st, cls.category, { needsHuman, qualityFlags: flags, urgency: cls.urgency, kbAnswered: kbRes.data.status === "answered" });
  if (verdict.ok) {  // SIMULATED send; every Nth auto-send is sampled for human audit
    st.autoSentCount += 1;
    rec = { ...rec, status: "auto_sent", finalText: draft.reply, unchanged: true, audit: st.autoSentCount % AUDIT_EVERY === 0 ? "pending" : undefined };
  }
  store.db.records.unshift(rec); store.save();
  return rec;
}

export type ReviewAction = "approve" | "edit" | "reject" | "escalate";

export function reviewRecord(store: Store, id: string, action: ReviewAction, finalText?: string, reason?: string): Rec {
  const rec = store.db.records.find((r) => r.id === id);
  if (!rec) throw Object.assign(new Error("not found"), { status: 404 });
  if (rec.status !== "pending_review" && rec.status !== "kb_unavailable") throw Object.assign(new Error(`already ${rec.status}`), { status: 409 }); // no duplicate sends
  const sent = action === "approve" ? (rec.draft ?? finalText) : finalText;
  if (action !== "escalate" && (!sent || !sent.trim())) throw Object.assign(new Error("final_text required"), { status: 400 });
  rec.reviewedAt = new Date().toISOString(); rec.reason = reason;
  if (action === "escalate") rec.status = "escalated";
  else if (action === "reject") { rec.status = "rejected"; rec.finalText = sent; }
  else { rec.status = "sent"; rec.finalText = sent; }
  // Compare actual text, not the button clicked: "approve" with an edited body is NOT unchanged.
  const unchanged = rec.status === "sent" && rec.draft !== null && sent !== undefined && normalizeEq(rec.draft, sent);
  rec.unchanged = unchanged;
  if (rec.draft && sent) rec.editRatio = editRatioOf(rec.draft, sent);
  store.db.autonomy[rec.category] = applyOutcome(store.db.autonomy[rec.category], rec.category, { unchanged, qualityOk: rec.qualityFlags.length === 0 });
  store.save();
  return rec;
}
export function auditRecord(store: Store, id: string, ok: boolean): Rec {
  const rec = store.db.records.find((r) => r.id === id);
  if (!rec || rec.status !== "auto_sent") throw Object.assign(new Error("not an auto-sent record"), { status: 404 });
  rec.audit = ok ? "ok" : "bad";
  if (!ok) store.db.autonomy[rec.category] = applyOutcome(store.db.autonomy[rec.category], rec.category, { unchanged: false, qualityOk: false });
  store.save();
  return rec;
}

// ---------- offline mock (smoke tests only; real quality needs a real model) ----------
const RULES: [Category, RegExp][] = [
  ["refund_cancellation", /\b(refund|cancel|money back|chargeback)\b/i],
  ["quote_request", /\b(how much|quote|estimate|pricing for|cost of|price for)\b/i],
  ["follow_up", /\b(following up|follow up|any update|did you receive|checking in|still waiting|no reply)\b/i],
  ["complaint", /\b(unacceptable|disappointed|terrible|furious|worst|broke our|ruined|angry)\b/i],
  ["project_request", /\b(can you (add|build|create|develop|integrate)|we need a new|new feature|custom)\b/i],
  ["troubleshooting", /\b(not working|stopped working|error|fails?|failing|broken|can't|cannot|won't|doesn't work)\b/i],
  ["how_to", /\b(how (do|can|to)|where (do|can)|is it possible)\b/i],
];
registerMock("classify", (u) => {
  const subj = /Subject: (.*)/.exec(u)?.[1] ?? "";
  const body = u.split("\n\n").slice(1).join(" ");
  const text = `${subj} ${body}`;
  const category = RULES.find(([, re]) => re.test(text))?.[0] ?? "other";
  return JSON.stringify({ category, urgency: /urgent|asap|immediately/i.test(text) ? "high" : "normal", summary: subj || "Customer email",
    question_for_kb: ["how_to", "troubleshooting", "follow_up"].includes(category) || /\?/.test(text) ? subj : "" });
});
registerMock("draft", (u) => {
  const kb = /KNOWLEDGE:\n([\s\S]*?)\n\n<email>/.exec(u)?.[1] ?? "";
  const grounded = kb && !kb.startsWith("(none");
  return JSON.stringify({
    reply: grounded ? `Hi,\n\nThanks for reaching out. ${kb.split("\nSources:")[0]}\n\nThe Support Team`
      : "Hi,\n\nThanks for reaching out. A team member will review your message and get back to you shortly.\n\nThe Support Team",
    needs_human: !grounded, next_action: grounded ? "send" : "assign to expert", follow_up_days: null, makes_commitment: false });
});
