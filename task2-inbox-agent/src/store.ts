import { mkdirSync, readFileSync, renameSync, writeFileSync, existsSync } from "node:fs";
import { dirname } from "node:path";
import { freshState } from "./autonomy.js";
import { CATEGORIES, type AutonomyState, type Category, type Rec } from "./types.js";
import { DEFAULT_PROMPTS, type PromptBook } from "./prompts.js";

export interface Db { records: Rec[]; autonomy: Record<Category, AutonomyState>; prompts: PromptBook }

export class Store {
  db: Db;
  constructor(private path: string | null = process.env.DB_PATH ?? "data/db.json") {
    const autonomy = Object.fromEntries(CATEGORIES.map((c) => [c, freshState()])) as Record<Category, AutonomyState>;
    this.db = { records: [], autonomy, prompts: structuredClone(DEFAULT_PROMPTS) };
    if (this.path && existsSync(this.path)) this.db = { ...this.db, ...(JSON.parse(readFileSync(this.path, "utf8")) as Partial<Db>) };
  }
  save(): void {
    if (!this.path) return;
    mkdirSync(dirname(this.path), { recursive: true });
    writeFileSync(`${this.path}.tmp`, JSON.stringify(this.db, null, 2));
    renameSync(`${this.path}.tmp`, this.path); // atomic replace
  }
  activePrompt(name: keyof PromptBook) { return this.db.prompts[name].find((p) => p.active) ?? this.db.prompts[name][0]!; }
}
