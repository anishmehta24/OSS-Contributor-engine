import { type NextRequest, NextResponse } from "next/server";

/**
 * Optimistic auth guard.
 *
 * We do NOT verify the session signature here — that's FastAPI's job, and it
 * happens on every /api/* call. This proxy just blocks unauthenticated users
 * from rendering authed pages (avoids a flash of empty UI before the first
 * API call returns 401).
 *
 * The Next.js docs recommend keeping proxy logic optimistic (no DB / no
 * verification) so it stays fast; full auth checks belong close to data.
 */
const SESSION_COOKIE = "oss_engine_session";

// Routes that require a session — everything inside the (app) route group.
const PROTECTED_PREFIXES = [
  "/dashboard",
  "/profile",
  "/matches",
  "/investigations",
  "/pitches",
  "/settings",
];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  if (!isProtected) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (!hasSession) {
    const signin = new URL("/signin", request.url);
    // Preserve where the user was trying to go so we can return them there
    // after they finish OAuth. (Wire up read-side in Batch 22.)
    signin.searchParams.set("next", pathname);
    return NextResponse.redirect(signin);
  }

  return NextResponse.next();
}

export const config = {
  // Run on every route except Next internals, static assets, and the /api/*
  // proxy (FastAPI returns 401 itself for unauthenticated API calls).
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)",
  ],
};
