"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";

import { cn } from "@/lib/utils";

export const THEME_KEY = "study-abroad-theme";

type Theme = "light" | "dark";

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/**
 * Light/dark switch.
 *
 * The actual theme is applied by an inline script in the document head, before
 * first paint - this component only reflects and changes it. Deciding the
 * theme in React would mean rendering the wrong one for a frame first, which
 * is the flash of white every site with a dark mode is trying to avoid.
 *
 * Until it has mounted it renders a placeholder of the same size: the server
 * has no way to know which theme the browser will choose, so rendering an icon
 * would guarantee a hydration mismatch on half of all visits.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const [mounted, setMounted] = React.useState(false);
  const [theme, setTheme] = React.useState<Theme>("dark");

  React.useEffect(() => {
    setMounted(true);
    const stored = window.localStorage.getItem(THEME_KEY);
    setTheme(stored === "dark" || stored === "light" ? stored : systemTheme());
  }, []);

  // Someone who has not chosen explicitly should follow their system when it
  // changes - at sunset, say - rather than being stuck on whatever it was when
  // the tab opened.
  React.useEffect(() => {
    if (!mounted) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (window.localStorage.getItem(THEME_KEY)) return;
      const next = systemTheme();
      setTheme(next);
      document.documentElement.setAttribute("data-theme", next);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [mounted]);

  const toggle = React.useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // Private windows and blocked storage: the theme still applies for this
      // page, it simply will not be remembered.
    }
  }, [theme]);

  const base = cn(
    "inline-flex h-9 w-9 items-center justify-center rounded-[12px] border border-border bg-card text-ink transition-colors hover:bg-surface-soft",
    className,
  );

  if (!mounted) {
    return (
      <button
        type="button"
        className={base}
        aria-label="Toggle theme"
        title="Toggle theme"
        disabled
        tabIndex={-1}
        suppressHydrationWarning
      >
        <span className="h-4 w-4 opacity-0" aria-hidden />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className={base}
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      suppressHydrationWarning
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" aria-hidden />
      ) : (
        <Moon className="h-4 w-4" aria-hidden />
      )}
    </button>
  );
}
