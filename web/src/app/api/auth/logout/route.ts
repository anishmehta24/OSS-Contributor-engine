import { NextResponse } from "next/server";
import { cookies } from "next/headers";

/**
 * Sign-out.
 *
 * The cookie that authenticates us lives on the Next.js origin (port 3000),
 * so FastAPI alone can't clear it via Set-Cookie — the browser would ignore
 * a Set-Cookie from a different origin. We do it here instead.
 *
 * The rewrite rule for `/api/auth/:path*` in next.config.ts is overridden
 * for this exact path by the filesystem route, per Next.js's execution
 * order (filesystem > afterFiles rewrites). All OTHER /api/auth/* paths
 * still pass through to FastAPI unchanged.
 */
const SESSION_COOKIE = "oss_engine_session";
const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8000";

export async function POST(request: Request) {
  const c = await cookies();
  const session = c.get(SESSION_COOKIE);

  // Best-effort tell FastAPI too — useful when prod runs both on one domain.
  // We ignore errors here; the cookie clear below is what actually logs the
  // user out from this frontend's perspective.
  if (session) {
    try {
      await fetch(`${FASTAPI_URL}/auth/logout`, {
        method: "POST",
        headers: { Cookie: `${session.name}=${session.value}` },
        cache: "no-store",
      });
    } catch {
      /* swallow — user is still getting signed out locally */
    }
  }

  const response = NextResponse.redirect(new URL("/", request.url), {
    // 303 forces the browser to GET the redirect target even though we
    // arrived via POST (form submission).
    status: 303,
  });
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 0,
    path: "/",
  });
  return response;
}
