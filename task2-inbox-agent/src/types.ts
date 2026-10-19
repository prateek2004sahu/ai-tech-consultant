import { z } from "zod";

export const CATEGORIES = [
  "how_to", "troubleshooting", "project_request", "refund_cancellation",
  "complaint", "quote_request", "follow_up", "other",
] as const;
export type Category = (typeof CATEGORIES)[number];
export type Risk = "low" | "medium" | "high";

export const RISK: Record<Category, Risk> = {
  how_to: "low", troubleshooting: "medium", follow_up: "medium", other: "medium",
  project_request: "high", quote_request: "high", refund_cancellation: "high", complaint: "high",
};

export const ClassificationSchema = z.object({
  category: z.enum(CATEGORIES),
  urgency: z.enum(["low", "normal", "high"]),
  summary: z.string().min(1),
  question_for_kb: z.string(),
});
export type Classification = z.infer<typeof ClassificationSchema>;

export const DraftSchema = z.object({
  reply: z.string().min(1),
  needs_human: z.boolean(),
  next_action: z.string(),
  follow_up_days: z.number().int().min(0).nullable(),
  makes_commitment: z.boolean(),
});
export type DraftOut = z.infer<typeof DraftSchema>;

export const EmailInSchema = z.object({
  from: z.string().min(3).max(200),
  subject: z.string().min(1).max(300),
  body: z.string().min(1).max(10000),
  thread_context: z.string().max(5000).optional(),
});
export type EmailIn = z.infer<typeof EmailInSchema>;

export const KbResponseSchema = z.object({
  answer: z.string(),
  status: z.enum(["answered", "insufficient_evidence"]),
  sources: z.array(z.object({ title: z.string(), url: z.string(), relevance: z.number() })),
  images: z.array(z.string()).default([]),
  top_score: z.number(),
  needs_human: z.boolean(),
  escalation_id: z.number().nullable(),
});
export type KbOk = z.infer<typeof KbResponseSchema>;
export type KbResult =
  | { ok: true; data: KbOk }
  | { ok: false; error: string };

export type Status =
  | "pending_review" | "sent" | "rejected" | "escalated" | "auto_sent" | "kb_unavailable";

export interface Rec {
  id: string;
  email: EmailIn;
  category: Category;
  urgency: "low" | "normal" | "high";
  risk: Risk;
  summary: string;
  kb: KbResult;
  draft: string | null;
  needsHuman: boolean;
  qualityFlags: string[];
  draftPromptVersion: number;
  classifyPromptVersion: number;
  model: string;
  status: Status;
  finalText?: string;
  unchanged?: boolean;
  editRatio?: number;
  reason?: string;
  createdAt: string;
  reviewedAt?: string;
  audit?: "pending" | "ok" | "bad";
}

export interface AutonomyState {
  consecutive: number;
  eligible: boolean;
  enabled: boolean;
  autoSentCount: number;
  history: string[]; // audit trail of state changes
}
