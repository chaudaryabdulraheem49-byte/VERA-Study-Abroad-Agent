"use client";

import * as React from "react";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";

export default function Home() {
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState<boolean>(false);

  return (
    <div className="site-shell">
      {/* Topbar */}
      <header className="topbar" aria-label="Primary navigation">
        <Link className="brand" href="/" aria-label="Orbitly home">
          <span className="brand-mark" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </span>
          <span className="brand-name">ORBITLY</span>
        </Link>

        <nav
          className={`nav-links ${mobileMenuOpen ? "is-mobile-open !flex !flex-col !top-[70px] !bg-[#07101a] !border-line !z-50" : ""}`}
        >
          <a className="nav-link is-active" href="#top">
            Overview
          </a>
          <a className="nav-link" href="#how-it-works">
            How it works
          </a>
          <Link className="nav-link" href="/converter">
            Grade Converter
          </Link>
          <Link className="nav-link" href="/discovery">
            Universities
          </Link>
          <a className="nav-link" href="#faq">
            FAQ
          </a>
        </nav>

        <div className="topbar-actions">
          <ThemeToggle />
          <Link className="button button-dark" href="/chat">
            Find my match <span className="button-arrow">↗</span>
          </Link>
        </div>

        <button
          className="mobile-menu"
          type="button"
          aria-label="Open navigation"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          <span></span>
          <span></span>
        </button>
      </header>

      {/* Main Content */}
      <main id="top">
        {/* Hero Section */}
        <section className="hero-section" aria-labelledby="hero-title">
          <div className="hero-backdrop" aria-hidden="true">
            <span className="hero-halo"></span>
            <span className="hero-grid"></span>
            <span className="hero-sweep sweep-one"></span>
            <span className="hero-sweep sweep-two"></span>
          </div>
          <div className="hero-noise" aria-hidden="true"></div>

          <div className="hero-content">
            <div className="eyebrow reveal">
              <span className="eyebrow-dot"></span> The intelligent route to your next chapter
            </div>
            <h1 id="hero-title" className="hero-title reveal reveal-delay-1">
              Find the place
              <br />
              <em>you’ll thrive.</em>
            </h1>
            <p className="hero-copy reveal reveal-delay-2">
              Orbitly reads between the lines of your ambitions to surface
              universities that feel like <strong>your kind of possible.</strong>
            </p>
            <div className="hero-actions reveal reveal-delay-3">
              <Link className="button button-primary" href="/chat">
                Map my future <span className="button-arrow">↗</span>
              </Link>
              <a className="text-link" href="#how-it-works">
                See how it thinks <span>↓</span>
              </a>
            </div>
            <div className="hero-footnote reveal reveal-delay-4">
              <span className="signal-line"></span>
              <span>Built for curious minds crossing borders</span>
            </div>
          </div>

          <div className="hero-orbit-orb orb-one" aria-hidden="true"></div>
          <div className="hero-orbit-orb orb-two" aria-hidden="true"></div>
          <div className="hero-coordinate" aria-hidden="true">
            <span>40.7128° N</span>
            <span>74.0060° W</span>
          </div>
          <div className="hero-scroll-cue" aria-hidden="true">
            <span className="scroll-line"></span>
            <span>Scroll to explore</span>
          </div>
        </section>

        {/* How It Thinks Section */}
        <section
          className="story-section section-shell"
          id="how-it-works"
          aria-labelledby="story-title"
        >
          <div className="section-kicker">
            <span>01</span>
            <span className="kicker-rule"></span>
            <span>HOW IT THINKS</span>
          </div>
          <div className="story-heading">
            <h2 id="story-title">
              Not a database.
              <br />
              <span>A point of view.</span>
            </h2>
            <p>
              Good guidance feels less like a search result and more like someone
              finally asking the right question.
            </p>
          </div>
          <div className="story-rail">
            <article className="story-card story-card-dark">
              <span className="card-index">01 / LISTEN</span>
              <div className="card-symbol">⌁</div>
              <h3>Start with the why.</h3>
              <p>
                Your goals, your pace, your non-negotiables. We look for the
                signal behind the search.
              </p>
              <span className="card-caption">The human layer</span>
            </article>

            <article className="story-card story-card-light">
              <span className="card-index">02 / CONNECT</span>
              <div className="card-symbol">✳</div>
              <h3>Draw the invisible line.</h3>
              <p>
                We connect your signals to programs, cities, cultures, and the
                everyday life around campus.
              </p>
              <span className="card-caption">The context layer</span>
            </article>

            <article className="story-card story-card-coral">
              <span className="card-index">03 / ARRIVE</span>
              <div className="card-symbol">↗</div>
              <h3>Move with clarity.</h3>
              <p>
                Walk away with a shortlist that sounds like you — and a next step
                you can act on today.
              </p>
              <span className="card-caption">The momentum layer</span>
            </article>
          </div>
        </section>

        {/* CTA Section */}
        <section
          className="cta-section section-shell"
          id="faq"
          aria-labelledby="cta-title"
        >
          <div className="cta-mark" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </div>
          <div className="cta-content">
            <span className="section-kicker section-kicker-center">
              <span>02</span>
              <span className="kicker-rule"></span>
              <span>YOUR NEXT MOVE</span>
            </span>
            <h2 id="cta-title">
              The right place
              <br />
              <em>changes everything.</em>
            </h2>
            <p>
              Start with a few signals. Leave with a direction that feels
              distinctly yours.
            </p>
            <Link className="button button-primary" href="/chat">
              Begin the orbit <span className="button-arrow">↗</span>
            </Link>
          </div>
          <div className="cta-aside">
            <span className="aside-label">ORBITLY / 001</span>
            <span className="aside-text">
              A more human way
              <br />
              to study abroad.
            </span>
            <span className="aside-coordinate">
              51.5072° N
              <br />
              0.1276° W
            </span>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="footer">
        <Link className="brand" href="#top">
          <span className="brand-mark" aria-hidden="true">
            <span></span>
            <span></span>
            <span></span>
          </span>
          <span className="brand-name">ORBITLY</span>
        </Link>
        <span>© 2026 Orbitly AI</span>
        <span>Made for the next chapter</span>
        <a href="#top" className="back-top">
          Back to top ↑
        </a>
      </footer>
    </div>
  );
}
