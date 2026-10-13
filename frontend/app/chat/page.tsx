"use client";

import * as React from "react";
import Link from "next/link";
import { HelpCircle } from "lucide-react";

import { UserButton } from "@/components/auth/user-button";
import { ChatWindow } from "@/components/chat/chat-window";
import { SidebarHistory } from "@/components/chat/sidebar-history";
import { SideDock } from "@/components/side-dock";
import { ThemeToggle } from "@/components/theme-toggle";

export default function ChatPage() {
  // Lifted here because the sidebar (which thread is highlighted) and the chat
  // window (which thread to load) both need it.
  const [activeThreadId, setActiveThreadId] = React.useState<string | null>(null);
  // History is a panel rather than a permanent column: on a laptop the
  // conversation is the point, and a list that is always open costs it width.
  const [historyOpen, setHistoryOpen] = React.useState(false);

  return (
    <main className="relative flex h-dvh flex-col overflow-hidden">
      <div aria-hidden className="aurora" />

      <div className="relative z-10 mx-auto flex h-full w-full max-w-[1400px] gap-3 p-3 sm:gap-4 sm:p-4">
        <SideDock
          onToggleHistory={() => setHistoryOpen((open) => !open)}
          historyOpen={historyOpen}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-3 sm:gap-4">
          {/* Top bar: title, transcript status, help. */}
          <header className="glass relative z-20 flex shrink-0 items-center gap-3 rounded-[18px] px-4 py-3">
            <Link href="/" className="display-sm text-ink">
              Vera
            </Link>
            <span aria-hidden className="h-4 w-px bg-hairline" />
            <p className="caption-upper hidden text-muted-ink sm:block">
              Study abroad advisor
            </p>

            <div className="ml-auto flex items-center gap-2">
              <Link
                href="/"
                aria-label="What Vera does"
                className="flex h-9 w-9 items-center justify-center rounded-[12px] text-muted-ink transition-colors hover:bg-white/5 hover:text-ink"
              >
                <HelpCircle className="h-4 w-4" aria-hidden />
              </Link>
              <ThemeToggle />
              <UserButton />
            </div>
          </header>

          <div className="relative z-0 flex min-h-0 flex-1 gap-3 sm:gap-4">
            {historyOpen ? (
              <SidebarHistory
                className="hidden w-64 shrink-0 overflow-y-auto md:flex"
                activeThreadId={activeThreadId}
                onOpen={(id) => {
                  setActiveThreadId(id);
                  setHistoryOpen(false);
                }}
              />
            ) : null}

            <ChatWindow
              className="min-h-0 flex-1"
              threadId={activeThreadId}
              onThreadChange={setActiveThreadId}
            />
          </div>
        </div>
      </div>
    </main>
  );
}
