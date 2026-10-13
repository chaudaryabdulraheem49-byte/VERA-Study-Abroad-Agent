"use client";

import * as React from "react";
import { Loader2, MessageSquare, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { authHeader, isAuthConfigured } from "@/lib/auth-headers";

export interface ChatThread {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

/** "Today", "Yesterday", then a date - which is how people look for a conversation. */
function when(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${then.getUTCDate()} ${months[then.getUTCMonth()]}`;
}

interface SidebarHistoryProps {
  activeThreadId?: string | null;
  onOpen?: (threadId: string) => void;
  className?: string;
}

/**
 * The signed-in student's saved conversations.
 *
 * Renders nothing at all when accounts are not configured or nobody is signed
 * in: an empty panel headed "Your conversations" implies the feature is broken
 * rather than absent.
 */
export function SidebarHistory({
  activeThreadId,
  onOpen,
  className,
}: SidebarHistoryProps) {
  const [mounted, setMounted] = React.useState(false);
  const [threads, setThreads] = React.useState<ChatThread[] | null>(null);
  const [enabled, setEnabled] = React.useState(isAuthConfigured);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const load = React.useCallback(async () => {
    if (!isAuthConfigured) {
      setEnabled(false);
      return;
    }
    try {
      const headers = await authHeader();
      if (!headers) {
        // Not signed in. Not an error - the middleware will have redirected
        // anyone who needed to be.
        setEnabled(false);
        return;
      }
      const response = await fetch("/api/history/threads", { headers });
      if (!response.ok) {
        setEnabled(false);
        return;
      }
      const data = await response.json();
      setEnabled(Boolean(data.enabled));
      setThreads(data.threads ?? []);
    } catch (error) {
      console.error("Could not load chat history:", error);
      setEnabled(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // A new conversation is saved with a label cut from the first message, then
  // retitled by the model a moment later. Without a second read the sidebar
  // keeps showing the truncated version until the page is reloaded, which is
  // the whole problem this was meant to fix.
  //
  // Two reads rather than polling: the rename happens once, shortly after the
  // thread appears, so a timer that never stops would be cost with no reader.
  React.useEffect(() => {
    if (!activeThreadId) return;
    const timers = [4000, 10000].map((delay) =>
      window.setTimeout(() => void load(), delay),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [activeThreadId, load]);

  // Re-fetch threads when a chat turn finishes so that intent-based or profile-based
  // retitling updates the sidebar in real time.
  React.useEffect(() => {
    let timer: number | null = null;
    const handleTurnDone = () => {
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => void load(), 2000);
    };
    window.addEventListener("vera:turn_done", handleTurnDone);
    return () => {
      if (timer) window.clearTimeout(timer);
      window.removeEventListener("vera:turn_done", handleTurnDone);
    };
  }, [load]);

  const remove = React.useCallback(
    async (threadId: string) => {
      // Optimistic: removing a row from a list is trivially undoable by
      // reloading, and waiting on a round trip to redraw feels broken.
      setThreads((current) => current?.filter((t) => t.id !== threadId) ?? null);
      try {
        const headers = await authHeader();
        if (!headers) return;
        await fetch(`/api/history/threads/${threadId}`, {
          method: "DELETE",
          headers,
        });
      } catch (error) {
        console.error("Could not delete that conversation:", error);
        void load(); // Put it back - the delete did not happen.
      }
    },
    [load],
  );

  if (!mounted || !enabled) return null;

  return (
    <aside
      className={cn(
        "flex flex-col gap-3 rounded-[16px] border border-border bg-card p-4",
        className,
      )}
      aria-label="Saved conversations"
    >
      <h2 className="caption-upper text-muted-foreground">Your conversations</h2>

      {threads === null ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          Loading...
        </p>
      ) : threads.length === 0 ? (
        <p className="text-sm leading-[1.55] text-muted-foreground">
          Nothing saved yet. This conversation will appear here once you have
          said something.
        </p>
      ) : (
        <ul className="flex flex-col gap-1">
          {threads.map((thread) => (
            <li key={thread.id} className="group relative">
              <button
                type="button"
                onClick={() => onOpen?.(thread.id)}
                className={cn(
                  "flex w-full items-start gap-2.5 rounded-[12px] px-3 py-2.5 pr-9 text-left transition-colors hover:bg-surface-soft",
                  thread.id === activeThreadId && "bg-surface-soft",
                )}
              >
                <MessageSquare
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">
                    {thread.title}
                  </span>
                  <span className="block text-xs text-muted-foreground" suppressHydrationWarning>
                    {when(thread.updated_at)}
                  </span>
                </span>
              </button>

              <button
                type="button"
                onClick={() => void remove(thread.id)}
                // Visible on hover for a mouse, and always once focused, so it
                // is reachable from the keyboard rather than hidden from it.
                className="absolute right-2 top-2.5 rounded-[8px] p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus:opacity-100 group-hover:opacity-100"
                aria-label={`Delete "${thread.title}"`}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
