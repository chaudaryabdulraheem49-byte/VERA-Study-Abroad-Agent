"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export const THEME_KEY = "orbitly-theme";
export const LEGACY_THEME_KEY = "study-abroad-theme";

type Theme = "light" | "dark";

function getSystemTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function ThemeToggle({
  className,
  showLabel = true,
}: {
  className?: string;
  showLabel?: boolean;
}) {
  const [mounted, setMounted] = React.useState(false);
  const [theme, setTheme] = React.useState<Theme>("dark");

  React.useEffect(() => {
    setMounted(true);
    const stored =
      window.localStorage.getItem(THEME_KEY) ||
      window.localStorage.getItem(LEGACY_THEME_KEY);
    const active =
      stored === "dark" || stored === "light" ? (stored as Theme) : getSystemTheme();
    setTheme(active);
    document.documentElement.setAttribute("data-theme", active);
  }, []);

  React.useEffect(() => {
    if (!mounted) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (
        window.localStorage.getItem(THEME_KEY) ||
        window.localStorage.getItem(LEGACY_THEME_KEY)
      ) {
        return;
      }
      const next = getSystemTheme();
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
      window.localStorage.setItem(LEGACY_THEME_KEY, next);
    } catch {
      // Ignore blocked storage
    }
  }, [theme]);

  if (!mounted) {
    return (
      <button
        type="button"
        className={cn("theme-toggle", className)}
        aria-label="Switch theme"
        disabled
        tabIndex={-1}
        suppressHydrationWarning
      >
        <span className="theme-toggle-icon" aria-hidden="true">
          ◐
        </span>
        {showLabel && <span>Light mode</span>}
      </button>
    );
  }

  const isLight = theme === "light";

  return (
    <button
      type="button"
      onClick={toggle}
      className={cn("theme-toggle", className)}
      aria-label={isLight ? "Switch to dark theme" : "Switch to light theme"}
      suppressHydrationWarning
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        ◐
      </span>
      {showLabel && (
        <span data-theme-label>{isLight ? "Dark mode" : "Light mode"}</span>
      )}
    </button>
  );
}
