/**
 * Server-side FastAPI client.
 *
 * Use ONLY inside Server Components and Route Handlers. The browser's
 * `/api/*` requests are rewritten by Next.js to FastAPI and carry the
 * session cookie automatically — but server-to-server fetches need an
 * absolute URL and the cookie forwarded explicitly.
 *
 * Returns `null` on 401/404 instead of throwing so pages can render an
 * "empty state" without a try/catch on every call. Throws on real errors
 * (5xx, network, decode), which will hit error.tsx.
 */
import "server-only";
import { cookies } from "next/headers";
import type {
  CostSummary,
  DbStats,
  FeaturesResponse,
  HealthResponse,
  InvestigationRow,
  MatchesResponse,
  Me,
  PilotRun,
  SkillProfile,
} from "./types";

const SESSION_COOKIE = "oss_engine_session";
// Strip any trailing slash so `new URL("auth/me", `${FASTAPI_URL}/`)` never
// yields a double-slash path (`...onrender.com//auth/me`), which FastAPI 404s
// on. The Next.js rewrite in next.config.ts does the same — keep them in sync.
const FASTAPI_URL = (process.env.FASTAPI_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

type FetchOpts = {
  /** Pass `false` to send the request without cookies (e.g., public health check). */
  withSession?: boolean;
  /** Query params, serialized to a search string. */
  search?: Record<string, string | number | boolean>;
  /** Treat these statuses as a valid "no data" result and return null. */
  nullOn?: number[];
};

async function api<T>(
  path: string,
  { withSession = true, search, nullOn = [401, 404, 409] }: FetchOpts = {},
): Promise<T | null> {
  const url = new URL(path.replace(/^\//, ""), `${FASTAPI_URL}/`);
  if (search) {
    for (const [k, v] of Object.entries(search)) {
      url.searchParams.set(k, String(v));
    }
  }

  const headers = new Headers();
  if (withSession) {
    const c = await cookies();
    const session = c.get(SESSION_COOKIE);
    if (session) {
      headers.set("Cookie", `${session.name}=${session.value}`);
    }
  }

  const res = await fetch(url, {
    headers,
    // We fetch fresh on every render — dashboard data is per-user and
    // changes often. ISR/SSG would mix users' data, which is unsafe.
    cache: "no-store",
  });

  if (nullOn.includes(res.status)) return null;
  if (!res.ok) {
    throw new Error(`FastAPI ${path} -> ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Public helpers — each one is a thin typed wrapper around api().
// ---------------------------------------------------------------------------

export const fapi = {
  me: () => api<Me>("/auth/me"),
  health: () => api<HealthResponse>("/health", { withSession: false, nullOn: [] }),
  features: () =>
    api<FeaturesResponse>("/features", { withSession: false, nullOn: [] }),

  /** /users/me returns `{profile: SkillProfile}` — unwrap for ergonomic call sites. */
  async profile(): Promise<SkillProfile | null> {
    const wrapped = await api<{ profile: SkillProfile }>("/users/me");
    return wrapped?.profile ?? null;
  },

  matches: (params: { top?: number; difficulty?: string; explain?: boolean; mode?: string }) =>
    api<MatchesResponse>("/users/me/matches", {
      search: {
        top: params.top ?? 5,
        difficulty: params.difficulty ?? "any",
        explain: params.explain ?? false,
        mode: params.mode ?? "general",
      },
    }),

  recentInvestigations: (limit: number = 5) =>
    api<InvestigationRow[]>("/investigations", { search: { limit } }),

  investigation: (id: string) => api<InvestigationRow>(`/investigations/${id}`),

  investigationCost: (id: string) =>
    api<CostSummary>(`/investigations/${id}/cost`),

  /** Latest pilot run for an investigation, or null if none has been started. */
  latestPilot: (investigationId: string) =>
    api<PilotRun>(`/investigations/${investigationId}/pilot`),

  globalCost: () => api<CostSummary>("/admin/cost"),

  /** /admin/stats currently has no auth gate — fine for the landing page. */
  dbStats: () => api<DbStats>("/admin/stats", { withSession: false }),
};
