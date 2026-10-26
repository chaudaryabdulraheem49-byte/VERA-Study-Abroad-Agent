import type { Metadata } from "next";
import { DM_Mono, JetBrains_Mono, Space_Grotesk } from "next/font/google";

import "./globals.css";

const dmMono = DM_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-dm-mono",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Orbitly — Study abroad, better matched",
  description:
    "Orbitly is the AI study-abroad advisor that finds the university fit behind your ambitions.",
};

const APPLY_THEME = `
(function () {
  try {
    var stored = localStorage.getItem('orbitly-theme') || localStorage.getItem('study-abroad-theme');
    var dark = stored
      ? stored === 'dark'
      : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch (e) {
    // Blocked storage: fall through to the CSS media query
  }
})();
`;

const STRIP_EXTENSION_ATTRIBUTES = `
(function () {
  function strip(node) {
    if (!node || node.nodeType !== 1 || !node.attributes) return;
    for (var i = node.attributes.length - 1; i >= 0; i--) {
      var name = node.attributes[i].name;
      if (name && (name.indexOf('bis_') === 0 || name.indexOf('__processed') === 0)) {
        node.removeAttribute(name);
      }
    }
  }

  function stripTree(node) {
    if (!node || node.nodeType !== 1) return;
    strip(node);
    if (node.querySelectorAll) {
      var els = node.querySelectorAll('[bis_skin_checked], [bis_size], [bis_register], [class*="bis_"]');
      for (var i = 0; i < els.length; i++) {
        strip(els[i]);
      }
    }
  }

  // 1. Immediately clean elements that were already parsed before this script executed
  if (document.documentElement) {
    stripTree(document.documentElement);
  }

  if (typeof MutationObserver !== 'function') return;

  // 2. Observe subsequent attribute mutations and dynamic child insertions
  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var record = records[i];
      if (record.type === 'attributes') {
        if (record.attributeName && (record.attributeName.indexOf('bis_') === 0 || record.attributeName.indexOf('__processed') === 0)) {
          record.target.removeAttribute(record.attributeName);
        }
      } else if (record.type === 'childList') {
        var added = record.addedNodes;
        for (var j = 0; j < added.length; j++) {
          stripTree(added[j]);
        }
      }
    }
  });

  observer.observe(document.documentElement, {
    attributes: true,
    childList: true,
    subtree: true,
  });
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
      className={`${dmMono.variable} ${spaceGrotesk.variable} ${jetbrains.variable}`}
      suppressHydrationWarning
    >
      <body
        className="site-shell min-h-dvh antialiased"
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
