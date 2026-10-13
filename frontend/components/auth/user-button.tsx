"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogOut, User as UserIcon } from "lucide-react";
import type { User } from "@supabase/supabase-js";

import { Button } from "@/components/ui/button";
import { createClient, isAuthConfigured } from "@/lib/supabase/client";

/** Initials for the avatar, from whatever the account actually has. */
function initials(user: User): string {
  const name =
    (user.user_metadata?.full_name as string | undefined) ??
    (user.user_metadata?.name as string | undefined) ??
    user.email ??
    "";
  const parts = name.split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/**
 * Avatar, email and sign-out.
 *
 * Renders a sign-in link when nobody is signed in and nothing at all when
 * Supabase is not configured - a sign-in button that cannot work is worse than
 * no button.
 */
export function UserButton() {
  const router = useRouter();
  const [user, setUser] = React.useState<User | null>(null);
  const [mounted, setMounted] = React.useState(false);
  const [ready, setReady] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
    if (!isAuthConfigured) {
      setReady(true);
      return;
    }
    const supabase = createClient();

    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user);
      setReady(true);
    });

    // Signing out in another tab should sign this one out too.
    const { data: subscription } = supabase.auth.onAuthStateChange(
      (_event, session) => setUser(session?.user ?? null),
    );
    return () => subscription.subscription.unsubscribe();
  }, []);

  const signOut = React.useCallback(async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    setOpen(false);
    router.push("/");
    // The server components still hold the old session until this runs.
    router.refresh();
  }, [router]);

  if (!isAuthConfigured) return null;

  // A fixed-size placeholder, so the header does not jump once the user loads.
  if (!mounted || !ready) {
    return <span className="inline-block h-9 w-9" aria-hidden suppressHydrationWarning />;
  }

  if (!user) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href="/login">Sign in</Link>
      </Button>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-teal text-sm font-semibold text-white transition-opacity hover:opacity-90"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.email ?? "your account"}`}
      >
        {initials(user)}
      </button>

      {open ? (
        <>
          {/* Click-away layer. A plain overlay rather than a document listener:
              it cannot miss a click that lands inside another handler first. */}
          <button
            type="button"
            className="fixed inset-0 z-10 cursor-default"
            aria-hidden
            tabIndex={-1}
            onClick={() => setOpen(false)}
          />
          <div
            role="menu"
            className="absolute right-0 z-20 mt-2 w-64 rounded-[16px] border border-border bg-card p-2"
          >
            <div className="flex items-center gap-3 rounded-[12px] px-3 py-2.5">
              <UserIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate text-sm text-body" title={user.email ?? ""}>
                {user.email}
              </span>
            </div>
            <button
              type="button"
              role="menuitem"
              onClick={() => void signOut()}
              className="flex w-full items-center gap-3 rounded-[12px] px-3 py-2.5 text-left text-sm text-ink transition-colors hover:bg-surface-soft"
            >
              <LogOut className="h-4 w-4 shrink-0" aria-hidden />
              Sign out
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
