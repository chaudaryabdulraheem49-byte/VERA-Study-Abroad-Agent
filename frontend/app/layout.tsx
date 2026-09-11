import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Study Abroad Agent - Smart Diagnostics",
  description:
    "Conversational study-abroad advisor: transcript OCR and deterministic US, German and UK grade conversion.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // Browser extensions mutate <html> and <body> before React hydrates -
    // Bitdefender stamps bis_skin_checked / bis_register, password managers and
    // dark-mode extensions do the same. Suppressing here silences that noise
    // without masking real bugs: suppressHydrationWarning applies only to the
    // element it is set on, so any genuine mismatch inside the app still warns.
    <html lang="en" suppressHydrationWarning>
      <body
        className="min-h-dvh bg-background text-foreground antialiased"
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
