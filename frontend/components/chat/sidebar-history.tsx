"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, MessageSquare, Trash2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { authHeader, isAuthConfigured } from "@/lib/auth-headers";

export interface ChatThread {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

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
  onNewChat?: () => void;
  onClose?: () => void;
  className?: string;
}

export function SidebarHistory({
  activeThreadId,
  onOpen,
  onNewChat,
  onClose,
  className,
}: SidebarHistoryProps) {
  const [mounted, setMounted] = React.useState(false);
  const [threads, setThreads] = React.useState<ChatThread[] | null>(null);
  const [isSignedIn, setIsSignedIn] = React.useState(true);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const load = React.useCallback(async () => {
    if (!isAuthConfigured) {
      setIsSignedIn(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const headers = await authHeader();
      if (!headers) {
        setIsSignedIn(false);
        setLoading(false);
        return;
      }
      setIsSignedIn(true);
      const response = await fetch("/api/history/threads", { headers });
      if (!response.ok) {
        setThreads([]);
        setLoading(false);
        return;
      }
      const data = await response.json();
      setThreads(data.threads ?? []);
    } catch (error) {
      console.error("Could not load chat history:", error);
      setThreads([]);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    if (!activeThreadId) return;
    const timers = [4000, 10000].map((delay) =>
      window.setTimeout(() => void load(), delay),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [activeThreadId, load]);

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
        void load();
      }
    },
    [load],
  );

  if (!mounted) return null;

  return (
    <aside
      className={cn(
        "conversation-panel flex flex-col gap-3 rounded-[17px] border border-line p-4 min-w-[280px]",
        className,
      )}
      aria-label="Saved conversations"
    >
      <div className="flex items-center justify-between border-b border-line pb-3">
        <div>
          <span className="panel-kicker">HISTORY</span>
          <h2 className="font-display text-xs font-medium tracking-wider text-ink">
            CONVERSATIONS
          </h2>
        </div>
        <div className="flex items-center gap-1">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-muted hover:text-ink"
              title="Close history panel"
              aria-label="Close history panel"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {!isSignedIn ? (
        <div className="my-auto flex flex-col items-center justify-center p-4 text-center">
          <span className="text-2xl text-accent mb-2">↶</span>
          <p className="font-display text-xs text-ink mb-1">
            Save your conversations
          </p>
          <p className="text-[12px] leading-[1.5] text-muted mb-4">
            Sign in to save multiple consultations and resume your university search anytime.
          </p>
          <Link
            href="/login?next=%2Fchat"
            className="button button-primary !py-2.5 !px-4 text-xs w-full justify-center"
          >
            Sign in to save <span className="button-arrow">↗</span>
          </Link>
        </div>
      ) : loading && threads === null ? (
        <p className="flex items-center gap-2 py-4 text-xs text-muted font-display">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden />
          Loading conversations...
        </p>
      ) : threads && threads.length === 0 ? (
        <div className="py-6 text-center">
          <p className="text-xs leading-[1.55] text-muted">
            No saved conversations yet. Conversations are automatically saved as you chat with Vera.
          </p>
        </div>
      ) : (
        <ul className="flex flex-1 flex-col gap-1 overflow-y-auto">
          {threads?.map((thread) => {
            const isActive = thread.id === activeThreadId;
            return (
              <li key={thread.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onOpen?.(thread.id)}
                  className={cn(
                    "flex w-full items-start gap-2.5 rounded-[10px] border border-transparent px-3 py-2.5 pr-8 text-left transition-all",
                    isActive
                      ? "border-accent/40 bg-accent/15 text-accent font-medium"
                      : "hover:bg-surface-soft text-muted hover:text-ink",
                  )}
                >
                  <MessageSquare
                    className={cn(
                      "mt-0.5 h-3.5 w-3.5 shrink-0",
                      isActive ? "text-accent" : "text-muted",
                    )}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium text-ink">
                      {thread.title}
                    </span>
                    <span
                      className="block font-display text-[9px] text-muted"
                      suppressHydrationWarning
                    >
                      {when(thread.updated_at)}
                    </span>
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => void remove(thread.id)}
                  className="absolute right-2 top-2.5 rounded-[6px] p-1 text-muted opacity-0 transition-opacity hover:text-red-400 focus:opacity-100 group-hover:opacity-100"
                  aria-label={`Delete "${thread.title}"`}
                  title="Delete conversation"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {isSignedIn && (
        <div className="border-t border-line pt-2 text-center">
          <span className="font-display text-[9px] text-muted uppercase tracking-wider">
            {threads?.length ?? 0} saved consultation{threads?.length === 1 ? "" : "s"}
          </span>
        </div>
      )}
    </aside>
  );
}
