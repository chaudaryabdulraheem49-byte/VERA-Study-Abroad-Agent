import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

export default function AuthLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <main className="relative min-h-dvh overflow-hidden">
      {/* The same aurora as the welcome page, so signing in feels like part
          of the product rather than a detour through a form. */}
      <div aria-hidden className="aurora" />

      <div className="relative z-10 mx-auto flex min-h-dvh max-w-[1280px] flex-col px-4 py-6 sm:px-8">
        <header className="flex items-center justify-between">
          <Link href="/" className="display-sm text-ink">
            Vera
          </Link>
          <ThemeToggle />
        </header>

        <div className="flex flex-1 items-center justify-center py-10">
          <div className="glass rise-in w-full max-w-md rounded-[18px] p-8 sm:p-10">
            {children}
          </div>
        </div>
      </div>
    </main>
  );
}
