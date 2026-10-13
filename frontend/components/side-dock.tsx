"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Calculator, Compass, History, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The left rail: new consultation, history, and the two standalone tools.
 *
 * Icon-only, which is normally a discoverability problem - so every item
 * carries both an `aria-label` and a visible tooltip on hover and focus. An
 * icon-only rail without either is the single most common way a dock like
 * this becomes unusable.
 */

interface DockItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

const ITEMS: DockItem[] = [
  { href: "/chat", label: "Consultation", icon: <Sparkles className="h-4 w-4" /> },
  { href: "/converter", label: "Grade converter", icon: <Calculator className="h-4 w-4" /> },
  { href: "/discovery", label: "University discovery", icon: <Compass className="h-4 w-4" /> },
];

export function SideDock({
  onToggleHistory,
  historyOpen,
}: {
  onToggleHistory?: () => void;
  historyOpen?: boolean;
}) {
  const pathname = usePathname();

  // `.glass` sets backdrop-filter, which makes every panel its own stacking
  // context. A tooltip's own z-index is therefore confined to this rail, and
  // later siblings paint over it - so the rail must outrank them here,
  // rather than the tooltip trying to outrank them from inside.
  return (
    <nav
      aria-label="Primary"
      className="glass relative z-30 flex shrink-0 flex-col items-center gap-2 rounded-[18px] p-2"
    >
      {/* Only the chat page passes a history toggle. The divider belongs to
          it, so on the tool pages neither renders and the rail does not open
          with a rule separating nothing from the links. */}
      {onToggleHistory ? (
        <>
          <DockButton
            label={historyOpen ? "Hide history" : "Show history"}
            onClick={onToggleHistory}
            active={historyOpen}
          >
            <History className="h-4 w-4" />
          </DockButton>

          <span aria-hidden className="my-1 h-px w-6 bg-hairline" />
        </>
      ) : null}

      {ITEMS.map((item) => (
        <DockLink
          key={item.href}
          item={item}
          active={pathname === item.href}
        />
      ))}
    </nav>
  );
}

/** Shared shell, so a link and a button in the rail cannot drift apart. */
const shell =
  "group relative flex h-10 w-10 items-center justify-center rounded-[12px] transition-colors duration-150";

function Tooltip({ label }: { label: string }) {
  return (
    <span
      role="tooltip"
      className="glass-raised pointer-events-none absolute left-full z-50 ml-2 hidden whitespace-nowrap rounded-[10px] px-2.5 py-1.5 text-xs text-ink group-hover:block group-focus-visible:block"
    >
      {label}
    </span>
  );
}

function DockLink({ item, active }: { item: DockItem; active: boolean }) {
  return (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      className={cn(
        shell,
        active
          ? "bg-cyan/15 text-cyan"
          : "text-muted-ink hover:bg-white/5 hover:text-ink",
      )}
    >
      {item.icon}
      <Tooltip label={item.label} />
    </Link>
  );
}

function DockButton({
  label,
  onClick,
  children,
  active,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={cn(
        shell,
        "cursor-pointer",
        active
          ? "bg-cyan/15 text-cyan"
          : "text-muted-ink hover:bg-white/5 hover:text-ink",
      )}
    >
      {children}
      <Tooltip label={label} />
    </button>
  );
}
