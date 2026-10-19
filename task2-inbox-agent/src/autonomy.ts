import { type AutonomyState, type Category, type Rec } from "./types.js";

/** Categories that must ALWAYS go through a human, even after 20 unchanged drafts (money, legal, reputation). */
export const NEVER_AUTO: ReadonlySet<Category> = new Set<Category>([
  "refund_cancellation", "complaint", "quote_request", "project_request", "other",
]);
export const THRESHOLD = Number(process.env.AUTONOMY_THRESHOLD ?? 20);
export const AUDIT_EVERY = Number(process.env.AUDIT_EVERY ?? 5);

/** "Same kind" = same category. "Without changing" = identical after trimming, lowercasing and collapsing whitespace. */
export const normalize = (s: string): string => s.toLowerCase().replace(/\s+/g, " ").trim();
export const isUnchanged = (draft: string, final: string): boolean => normalize(draft) === normalize(final);

/** Word-level edit ratio (0 = identical, 1 = completely different). Used for reporting, not for the rule. */
export function editRatio(a: string, b: string): number {
  const x = normalize(a).split(" "), y = normalize(b).split(" ");
  const dp: number[][] = Array.from({ length: x.length + 1 }, (_, i) => [i, ...Array(y.length).fill(0)]);
  for (let j = 0; j <= y.length; j++) dp[0]![j] = j;
  for (let i = 1; i <= x.length; i++)
    for (let j = 1; j <= y.length; j++)
      dp[i]![j] = Math.min(dp[i - 1]![j]! + 1, dp[i]![j - 1]! + 1, dp[i - 1]![j - 1]! + (x[i - 1] === y[j - 1] ? 0 : 1));
  return Math.max(x.length, y.length) === 0 ? 0 : dp[x.length]![y.length]! / Math.max(x.length, y.length);
}

export const freshState = (): AutonomyState => ({ consecutive: 0, eligible: false, enabled: false, autoSentCount: 0, history: [] });

const log = (s: AutonomyState, msg: string): void => { s.history.push(`${new Date().toISOString()} ${msg}`); };

/** Pure-ish: returns a new state after a human outcome. Any edit/reject/escalate/quality failure resets the streak. */
export function applyOutcome(prev: AutonomyState, category: Category, outcome: { unchanged: boolean; qualityOk: boolean }): AutonomyState {
  const s: AutonomyState = { ...prev, history: [...prev.history] };
  if (outcome.unchanged && outcome.qualityOk) {
    s.consecutive += 1;
    if (s.consecutive >= THRESHOLD && !s.eligible && !NEVER_AUTO.has(category)) {
      s.eligible = true; log(s, `eligible after ${s.consecutive} consecutive unchanged drafts`);
    }
  } else {
    if (s.consecutive > 0 || s.enabled) log(s, `streak reset (was ${s.consecutive}); unchanged=${outcome.unchanged} quality=${outcome.qualityOk}`);
    s.consecutive = 0; s.eligible = false;
    if (s.enabled) { s.enabled = false; log(s, "autonomy disabled: quality dropped"); }
  }
  return s;
}

export function canAutoSend(s: AutonomyState, category: Category, rec: Pick<Rec, "needsHuman" | "qualityFlags" | "urgency"> & { kbAnswered: boolean }): { ok: boolean; reason?: string } {
  if (NEVER_AUTO.has(category)) return { ok: false, reason: `category ${category} always needs a human` };
  if (!s.enabled || !s.eligible) return { ok: false, reason: "autonomy not enabled for this category" };
  if (!rec.kbAnswered) return { ok: false, reason: "no grounded knowledge answer" };
  if (rec.needsHuman || rec.qualityFlags.length) return { ok: false, reason: "draft failed quality checks" };
  if (rec.urgency === "high") return { ok: false, reason: "high urgency" };
  return { ok: true };
}
