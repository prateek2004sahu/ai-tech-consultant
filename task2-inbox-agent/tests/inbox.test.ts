import { describe, expect, it } from "vitest";
import { applyOutcome, canAutoSend, editRatio, freshState, isUnchanged, THRESHOLD } from "../src/autonomy.js";
import { processEmail, reviewRecord, auditRecord } from "../src/pipeline.js";
import { Store } from "../src/store.js";
import type { KbResult } from "../src/types.js";

const okKb = async (): Promise<KbResult> => ({ ok: true, data: { answer: "Open Design Settings, then Logo.", status: "answered", sources: [{ title: "Logo", url: "https://x/logo", relevance: 0.8 }], images: [], top_score: 0.8, needs_human: false, escalation_id: null } });
const downKb = async (): Promise<KbResult> => ({ ok: false, error: "Knowledge service unavailable" });
const mail = (subject: string, body: string) => ({ from: "a@b.com", subject, body });

describe("autonomy rule", () => {
  it("compares text, ignoring whitespace and case only", () => {
    expect(isUnchanged("Hello  World\n", " hello world")).toBe(true);
    expect(isUnchanged("Hello World", "Hello World!")).toBe(false);
    expect(editRatio("a b c d", "a b c d")).toBe(0);
  });
  it("becomes eligible after exactly THRESHOLD unchanged drafts and resets on any edit", () => {
    let s = freshState();
    for (let i = 0; i < THRESHOLD - 1; i++) s = applyOutcome(s, "how_to", { unchanged: true, qualityOk: true });
    expect(s.eligible).toBe(false);
    s = applyOutcome(s, "how_to", { unchanged: true, qualityOk: true });
    expect(s.eligible).toBe(true);
    s = applyOutcome(s, "how_to", { unchanged: false, qualityOk: true });
    expect(s.consecutive).toBe(0); expect(s.eligible).toBe(false);
  });
  it("never auto-sends refunds even when counters say eligible", () => {
    let s = freshState();
    for (let i = 0; i < THRESHOLD; i++) s = applyOutcome(s, "refund_cancellation", { unchanged: true, qualityOk: true });
    s.enabled = true; s.eligible = true;
    expect(canAutoSend(s, "refund_cancellation", { needsHuman: false, qualityFlags: [], urgency: "normal", kbAnswered: true }).ok).toBe(false);
  });
});

describe("pipeline (mock model, stub knowledge service)", () => {
  it("drafts a grounded reply with evidence", async () => {
    const st = new Store(null);
    const r = await processEmail(st, mail("How do I update my website logo?", "How do I replace the logo?"), okKb);
    expect(r.category).toBe("how_to"); expect(r.draft).toContain("Design Settings"); expect(r.status).toBe("pending_review");
  });
  it("does not fabricate a reply when the knowledge service is down", async () => {
    const st = new Store(null);
    const r = await processEmail(st, mail("How do I change colours?", "How do I change colours?"), downKb);
    expect(r.status).toBe("kb_unavailable"); expect(r.draft).toBeNull();
  });
  it("treats clicking approve on an edited draft as an edit, and blocks double sends", async () => {
    const st = new Store(null);
    const r = await processEmail(st, mail("How do I update my website logo?", "How do I replace the logo?"), okKb);
    reviewRecord(st, r.id, "edit", `${r.draft} Cheers`);
    expect(st.db.records[0]!.unchanged).toBe(false);
    expect(() => reviewRecord(st, r.id, "approve")).toThrow(/already/);
  });
  it("full loop: 20 unchanged how_to approvals -> eligible -> enable -> auto_sent -> bad audit disables", async () => {
    const st = new Store(null);
    for (let i = 0; i < THRESHOLD; i++) {
      const r = await processEmail(st, mail(`How do I update my logo ${i}?`, "How do I replace the logo?"), okKb);
      reviewRecord(st, r.id, "approve");
    }
    expect(st.db.autonomy.how_to.eligible).toBe(true);
    st.db.autonomy.how_to.enabled = true;
    const a = await processEmail(st, mail("How do I update my logo again?", "How do I replace the logo?"), okKb);
    expect(a.status).toBe("auto_sent");
    st.db.records[0]!.status = "auto_sent";
    auditRecord(st, a.id, false);
    expect(st.db.autonomy.how_to.enabled).toBe(false); expect(st.db.autonomy.how_to.consecutive).toBe(0);
  });
  it("flags commitments in drafts so they cannot auto-send", async () => {
    const st = new Store(null);
    const r = await processEmail(st, mail("Quote for redesign", "Could you give us a quote?"), async () => ({ ...(await okKb()), data: { ...(await okKb() as any).data, answer: "It costs $500." } }) as KbResult);
    expect(r.qualityFlags.length).toBeGreaterThan(0); expect(r.needsHuman).toBe(true);
  });
});
