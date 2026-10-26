"use client";

import * as React from "react";
import Link from "next/link";

import { UserButton } from "@/components/auth/user-button";
import { ChatWindow } from "@/components/chat/chat-window";
import { SidebarHistory } from "@/components/chat/sidebar-history";
import { SideDock } from "@/components/side-dock";
import { ThemeToggle } from "@/components/theme-toggle";

export default function ChatPage() {
  const [activeThreadId, setActiveThreadId] = React.useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = React.useState(false);

  return (
    <div className="app-page h-dvh max-h-dvh overflow-hidden">
      <div className="chat-shell h-full max-h-full overflow-hidden">
        <SideDock
          onToggleHistory={() => setHistoryOpen((open) => !open)}
          historyOpen={historyOpen}
        />

        <div className="chat-workspace h-full max-h-full overflow-hidden">
          <header className="app-topbar shrink-0">
            <Link className="brand" href="/" aria-label="Orbitly home">
              <span className="brand-mark" aria-hidden="true">
                <span></span>
                <span></span>
                <span></span>
              </span>
              <span className="brand-name">ORBITLY</span>
            </Link>
            <span className="app-separator"></span>
            <span className="app-context">
              <i></i> ADVISOR WORKSPACE
            </span>

            <div className="app-actions">
              <button
                type="button"
                onClick={() => setHistoryOpen((open) => !open)}
                className={`theme-toggle cursor-pointer font-display text-[10px] flex items-center gap-1.5 px-3 py-1.5 ${
                  historyOpen
                    ? "!border-[var(--accent)] !text-[var(--accent)] bg-[var(--accent)]/10"
                    : ""
                }`}
                aria-label="Toggle chat history"
                title="View past conversations"
              >
                <span className="theme-toggle-icon">↶</span>
                <span>History</span>
              </button>

              <Link
                className="app-help"
                href="/#how-it-works"
                aria-label="How Orbitly works"
                title="How Orbitly works"
              >
                ?
              </Link>
              <ThemeToggle showLabel={false} />
              <UserButton />
            </div>
          </header>

          <div className="relative z-0 flex min-h-0 flex-1 gap-3 sm:gap-4 overflow-hidden h-full">
            {historyOpen && (
              <>
                {/* Desktop sidebar */}
                <SidebarHistory
                  className="hidden w-72 shrink-0 overflow-y-auto md:flex h-full"
                  activeThreadId={activeThreadId}
                  onOpen={(id) => {
                    setActiveThreadId(id);
                  }}
                  onNewChat={() => {
                    setActiveThreadId(null);
                  }}
                  onClose={() => setHistoryOpen(false)}
                />

                {/* Mobile / tablet drawer overlay */}
                <div
                  className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 md:hidden"
                  onClick={() => setHistoryOpen(false)}
                >
                  <div
                    className="w-full max-w-sm"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <SidebarHistory
                      className="w-full max-h-[85vh] overflow-y-auto shadow-2xl"
                      activeThreadId={activeThreadId}
                      onOpen={(id) => {
                        setActiveThreadId(id);
                        setHistoryOpen(false);
                      }}
                      onNewChat={() => {
                        setActiveThreadId(null);
                        setHistoryOpen(false);
                      }}
                      onClose={() => setHistoryOpen(false)}
                    />
                  </div>
                </div>
              </>
            )}

            <ChatWindow
              className="min-h-0 flex-1 h-full overflow-hidden"
              threadId={activeThreadId}
              onThreadChange={setActiveThreadId}
              onToggleHistory={() => setHistoryOpen((open) => !open)}
              historyOpen={historyOpen}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
