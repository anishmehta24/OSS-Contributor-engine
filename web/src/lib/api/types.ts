/**
 * Shapes returned by the FastAPI backend.
 *
 * Hand-written for now to keep the build chain simple. Batch 26+ can replace
 * this with `openapi-typescript` codegen against `/openapi.json` once we
 * stop iterating on the API surface.
 */

export type Me = {
  id: number;
  github_login: string;
  github_id: number;
  name: string | null;
  has_oauth_token: boolean;
};

export type SkillProfile = {
  github_login: string;
  github_id: number;
  name: string | null;
  languages: string[];
  frameworks: string[];
  domains: string[];
  experience_signal: "junior" | "mid" | "senior" | null;
  summary: string | null;
  repos_analyzed: number;
  profiled_at: string; // ISO timestamp
};

export type RankedMatch = {
  issue_id: number;
  issue_number: number;
  repo_full_name: string;
  title: string;
  html_url: string;
  labels: string[];
  difficulty: "easy" | "medium" | "hard" | null;
  skill_match: number;
  repo_health: number;
  freshness: number;
  difficulty_match: number;
  impact: number;
  final_score: number;
  why_it_fits: string | null;
  issue_updated_at: string;
  stargazers_count: number;
};

export type MatchesResponse = {
  github_login: string;
  count: number;
  matches: RankedMatch[];
};

export type InvestigationRow = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  repo: string | null;
  issue_number: number | null;
  issue_url: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  markdown_report: string | null;
  pitch_md: string | null;
};

export type PitchResponse = {
  investigation_id: string;
  comment_md: string;
  asks_questions: boolean;
  estimated_timeline: string | null;
  tone: string;
  cached: boolean;
};

export type CostSummary = {
  scope: string;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  total_latency_ms: number;
  total_errors: number;
  per_agent: Array<{
    agent_name: string;
    calls: number;
    tokens_in: number;
    tokens_out: number;
    cost_usd: number;
    latency_ms: number;
    errors: number;
  }>;
};

export type HealthResponse = {
  status: "ok";
  version: string;
  services: { [name: string]: boolean };
};

// ---------------------------------------------------------------------------
// Pilot Coordinator (v3)
// ---------------------------------------------------------------------------

export type PilotStatus =
  | "queued"
  | "running"
  | "accepted"
  | "rejected"
  | "rate_limited"
  | "failed";

export type PilotRun = {
  id: string;
  investigation_id: string;
  status: PilotStatus;
  summary: string | null;
  attempts_made: number;
  accepted_attempt_number: number | null;
  accepted_diff: string | null;
  // Loosely-typed dump of the full ReviewerResult — we don't need its
  // shape on the client side for v1.
  transcript: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  // Push (Batch 34) — null until the accepted diff is pushed.
  fork_url: string | null;
  branch_ref: string | null;
  pushed_at: string | null;
  push_error: string | null;
  // Draft PR (Batch 35) — null until the PR is opened upstream.
  pr_url: string | null;
  pr_number: number | null;
  pr_opened_at: string | null;
  pr_error: string | null;
};

export type CreatePilotResponse = {
  pilot_id: string;
  status: "queued";
};

export type PushPilotResponse = {
  pilot_id: string;
  status: "push_queued";
};

export type OpenPRResponse = {
  pilot_id: string;
  status: "pr_queued";
};

export type DbStats = {
  users: number;
  user_skills: number;
  repos: number;
  issues: number;
  investigations: number;
  agent_runs: number;
  issues_with_embeddings: number;
};
