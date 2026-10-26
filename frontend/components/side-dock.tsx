"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

interface DockItem {
  href: string;
  label: string;
  symbol: string;
}

const ITEMS: DockItem[] = [
  { href: "/chat", label: "Advisor Consultation", symbol: "✧" },
  { href: "/discovery", label: "University Discovery", symbol: "◉" },
  { href: "/converter", label: "Grade Converter", symbol: "▦" },
];

export function SideDock({
  onToggleHistory,
  historyOpen,
}: {
  onToggleHistory?: () => void;
  historyOpen?: boolean;
}) {
  const pathname = usePathname();

  return (
    <aside className="chat-rail" aria-label="Workspace navigation">
      <Link className="rail-brand" href="/" aria-label="Orbitly home">
        <span className="brand-mark" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
      </Link>
      <div className="rail-divider"></div>

      {ITEMS.map((item) => {
        const isActive = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={item.label}
            title={item.label}
            className={cn("rail-icon", isActive && "is-active")}
          >
            <span>{item.symbol}</span>
          </Link>
        );
      })}

      <div className="rail-spacer"></div>

      {onToggleHistory && (
        <button
          type="button"
          onClick={onToggleHistory}
          aria-label={historyOpen ? "Close chat history" : "Open chat history"}
          title="Chat History (Past Conversations)"
          className={cn("rail-icon rail-history", historyOpen && "is-active !border-[var(--accent)] !text-[var(--accent)]")}
        >
          <span>↶</span>
        </button>
      )}
    </aside>
  );
}
