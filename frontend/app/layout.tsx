import type { Metadata } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans, Syne } from "next/font/google";

import "./globals.css";

// Three families, each with a job the others cannot do:
//   Syne              display, carrying the spec's high-tracking headings
//   Plus Jakarta Sans everything read as prose
//   JetBrains Mono    every figure a student acts on - grades, GPAs, credits,
//                     and the Bavarian formula's output
const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
  display: "swap",
});

const syne = Syne({
  subsets: ["latin"],
  variable: "--font-syne",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Vera - AI Study Abroad Advisor",
  description:
    "Conversational study-abroad advisor: transcript OCR and deterministic US, German and UK grade conversion.",
};

/**
 * Strip extension-injected attributes before React hydrates.
 *
 * Bitdefender's browser extension stamps `bis_skin_checked`, `bis_register`
 * and `__processed_<uuid>__` onto elements as soon as they appear in the DOM.
 * React compares the server HTML against the live DOM during hydration, sees
 * attributes the server never sent, and reports a mismatch it cannot patch.
 *
 * `suppressHydrationWarning` cannot fix this: it applies only to the element
 * it is set on, and the extension stamps elements anywhere in the tree -
 * including divs Next.js renders internally, which we do not author and cannot
 * annotate.
 *
 * So the attributes are removed instead. This script runs synchronously in
 * <head>, before any of the markup it guards exists, and watches for new ones
 * until hydration is over. Nothing the app renders depends on these
 * attributes; they are inert markers the extension uses to track what it has
 * already scanned, and it re-adds them harmlessly once we stop watching.
 *
 * This is a workaround for another program's behaviour, not a fix for a bug in
 * this app. Disabling the extension for localhost removes the cause, and this
 * script with it.
 */
const APPLY_THEME = `
(function () {
  try {
    var stored = localStorage.getItem('study-abroad-theme');
    var dark = stored
      ? stored === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {
    // Blocked storage: fall through to the CSS media query, which already
    // follows the system preference on its own.
  }
})();
`;

const STRIP_EXTENSION_ATTRIBUTES = `
(function () {
  function strip(node) {
    if (!node || node.nodeType !== 1 || !node.attributes) return;
    for (var i = node.attributes.length - 1; i >= 0; i--) {
      var name = node.attributes[i].name;
      if (name.indexOf('bis_') === 0 || name.indexOf('__processed') === 0) {
        node.removeAttribute(name);
      }
    }
  }

  if (typeof MutationObserver !== 'function') return;

  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      if (records[i].type === 'attributes') strip(records[i].target);
      else {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) strip(added[j]);
      }
    }
  });
  observer.observe(document.documentElement, {
    attributes: true,
    childList: true,
    subtree: true,
  });

  // Hydration is done by the time the load event has fired and the microtask
  // queue has drained. After that React no longer compares markup, so the
  // observer is pure overhead on a page that mutates constantly as messages
  // stream in - hence the disconnect rather than watching forever.
  function stop() {
    setTimeout(function () { observer.disconnect(); }, 0);
  }
  if (document.readyState === 'complete') stop();
  else window.addEventListener('load', stop, { once: true });
})();
`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // Still suppressed on the two elements we do author: the script below
    // cannot run before <html> and <body> themselves are parsed, so those two
    // can be stamped before the observer is watching.
    <html
      lang="en"
      data-theme="dark"
      className={`${jakarta.variable} ${syne.variable} ${jetbrains.variable}`}
      suppressHydrationWarning
    >
      <body
        className="min-h-dvh bg-background font-sans text-foreground antialiased"
        suppressHydrationWarning
      >
        {/*
          First in <body>, not in a hand-authored <head>.

          React 19 hoists inline <script> elements out of the tree, and in a
          manually written <head> the client re-renders them with an empty
          `__html` while the server sent the real one - which is the hydration
          mismatch this previously caused. Here they are ordinary body nodes
          and are left alone.

          The timing still holds. Both run before any of the markup they guard
          is parsed: the theme attribute lands on <html> before body content
          paints, so there is still no flash, and the attribute observer is
          watching before the extension can stamp anything below.
        */}
        <script
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: APPLY_THEME }}
        />
        <script
          suppressHydrationWarning
          dangerouslySetInnerHTML={{ __html: STRIP_EXTENSION_ATTRIBUTES }}
        />
        {children}
      </body>
    </html>
  );
}
