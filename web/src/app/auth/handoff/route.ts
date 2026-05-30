import { type NextRequest, NextResponse } from "next/server";

/**
 * Cross-origin OAuth bridge.
 *
 * FastAPI runs on a different port in dev (and possibly a different domain
 * in prod), so a Set-Cookie issued during its /auth/callback redirect can't
 * be sent on subsequent requests to the Next.js origin. The FastAPI callback
 * therefore appends the signed session value as `?session=<token>` and
 * redirects here. This handler takes the token off the URL and re-sets it
 * as an httpOnly cookie under THIS origin, then bounces the user to
 * /dashboard. After that all `/api/*` requests (proxied to FastAPI) carry
 * the cookie because the browser sees them as same-origin.
 *
 * The Streamlit frontend uses the same `?session=` URL handoff, so this
 * mirrors that behavior — we're not weakening security, just relocating
 * where the cookie lives.
 */

// 7 days, matches FastAPI's session_max_age_s default.
const SESSION_MAX_AGE_S = 7 * 24 * 60 * 60;
const SESSION_COOKIE = "oss_engine_session";

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("session");

  // If anything's missing, bounce back to sign-in rather than silently dropping.
  if (!token) {
    return NextResponse.redirect(
      new URL("/signin?error=missing_session", request.url),
    );
  }

  const response = NextResponse.redirect(new URL("/dashboard", request.url));
  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    // `secure: true` only behind HTTPS — localhost dev uses http.
    secure: process.env.NODE_ENV === "production",
    maxAge: SESSION_MAX_AGE_S,
    path: "/",
  });
  return response;
}
