import { redirect } from "next/navigation";
import { fapi } from "@/lib/api/server";
import { AppNav } from "@/components/app-nav";
import { AppFooter } from "@/components/app-footer";

/**
 * Shell for all authenticated pages.
 *
 * Despite proxy.ts already redirecting unauth requests away from `(app)`
 * routes, we double-check here because the proxy only inspects cookie
 * EXISTENCE, not signature validity. An expired or malformed cookie sails
 * past the proxy and lands here — we catch that case by calling FastAPI's
 * /auth/me (the source of truth) and redirecting on null.
 */
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const me = await fapi.me();
  if (!me) {
    redirect("/signin");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <AppNav me={me} />
      <main className="flex-1">{children}</main>
      <AppFooter />
    </div>
  );
}
