"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { createClient, isAuthConfigured } from "@/lib/supabase/client";

type Mode = "login" | "signup";

const COPY = {
  login: {
    title: "Welcome back",
    blurb: "Sign in to pick up your saved conversations.",
    action: "Sign in",
    swapPrompt: "New here?",
    swapLabel: "Create an account",
    swapHref: "/signup",
  },
  signup: {
    title: "Create your account",
    blurb: "Your conversations and diagnostic reports are saved to it.",
    action: "Create account",
    swapPrompt: "Already have an account?",
    swapLabel: "Sign in",
    swapHref: "/login",
  },
} as const;

/**
 * Email and password form for both signing in and signing up.
 *
 * One component for both because the two differ by a single Supabase call and
 * some wording - keeping them apart would mean two places to fix every time
 * the error handling or the redirect behaviour changes.
 */
export function AuthForm({ mode }: { mode: Mode }) {
  const copy = COPY[mode];
  const router = useRouter();
  const params = useSearchParams();

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  // Only a path is honoured: `?next=https://elsewhere` would otherwise make
  // this an open redirect, and the parameter comes from the URL.
  const requested = params.get("next") ?? "/chat";
  const next =
    requested.startsWith("/") && !requested.startsWith("//") ? requested : "/chat";

  // Surfaced from the auth callback, which only ever reflects a code.
  const callbackError = params.get("error");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    if (!isAuthConfigured) {
      setError(
        "Accounts are not configured on this deployment. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY.",
      );
      return;
    }

    setBusy(true);
    try {
      const supabase = createClient();

      if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: `${window.location.origin}/api/auth/callback?next=${encodeURIComponent(next)}`,
          },
        });
        if (error) throw error;

        // No session means the project requires email confirmation. Saying so
        // explicitly matters: otherwise the form looks like it did nothing.
        if (!data.session) {
          setNotice(
            `Check ${email} for a confirmation link. You can close this page.`,
          );
          return;
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (error) throw error;
      }

      // refresh() so the server components re-render with the new session;
      // push() alone would navigate with the old one still cached.
      router.push(next);
      router.refresh();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="display-sm text-ink">{copy.title}</h1>
      <p className="mt-2 text-[16px] leading-[1.55] text-body">{copy.blurb}</p>

      {callbackError ? (
        <p className="mt-6 flex items-start gap-2 rounded-[12px] border border-destructive/40 bg-destructive/[0.06] px-3 py-2.5 text-sm text-destructive">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {callbackError === "missing_code"
            ? "That confirmation link was incomplete. Try signing in directly."
            : "That confirmation link could not be used. It may have expired."}
        </p>
      ) : null}

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="email" className="caption-upper block text-muted-foreground">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="h-11 w-full rounded-[12px] border border-border bg-background px-4 text-[16px] text-ink outline-none transition-colors placeholder:text-muted-foreground focus:border-ink"
            placeholder="you@example.com"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="caption-upper block text-muted-foreground"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            // Tells a password manager which form it is looking at, so it
            // offers to save a new password rather than fill an old one.
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="h-11 w-full rounded-[12px] border border-border bg-background px-4 text-[16px] text-ink outline-none transition-colors placeholder:text-muted-foreground focus:border-ink"
            placeholder={mode === "signup" ? "At least 8 characters" : "••••••••"}
          />
        </div>

        {error ? (
          <p className="flex items-start gap-2 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {error}
          </p>
        ) : null}

        {notice ? (
          <p className="rounded-[12px] border border-border bg-surface-soft px-3 py-2.5 text-sm text-body">
            {notice}
          </p>
        ) : null}

        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Working...
            </>
          ) : (
            copy.action
          )}
        </Button>
      </form>

      <p className="mt-6 text-sm text-muted-foreground">
        {copy.swapPrompt}{" "}
        <Link href={copy.swapHref} className="font-semibold text-ink underline">
          {copy.swapLabel}
        </Link>
      </p>

      <p className="mt-6 border-t border-border pt-6 text-sm text-muted-foreground">
        You can also{" "}
        <Link href="/" className="underline">
          look around first
        </Link>
        . An account only exists so your conversations are there when you come
        back.
      </p>
    </div>
  );
}
