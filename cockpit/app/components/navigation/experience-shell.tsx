"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { formatDateTime, t } from "../../i18n";
import { glossary } from "../../i18n/glossary";
import { operationalEvidence } from "../../lib/presentation";
import { StatusBadge } from "../common/ui";
import {
  ExpertOnly,
  ViewModeProvider,
  ViewModeSwitch,
} from "../common/view-mode";

export type PublicSection =
  | "home"
  | "matches"
  | "hypotheses"
  | "observatory"
  | "learning"
  | "laboratory"
  | "results"
  | "method"
  | "expert";

const publicNavigation: Array<{
  key: PublicSection;
  href: string;
  label: ReturnType<typeof t>;
  icon: string;
}> = [
  { key: "home", href: "/robin-live", label: t("nav.home"), icon: "⌂" },
  { key: "matches", href: "/matchs", label: t("nav.matches"), icon: "◉" },
  {
    key: "hypotheses",
    href: "/hypotheses",
    label: t("home.hypotheses.title"),
    icon: "◇",
  },
  { key: "observatory", href: "/observatoire", label: t("nav.observatory"), icon: "◫" },
  { key: "results", href: "/resultats", label: t("nav.results"), icon: "↗" },
  { key: "method", href: "/methode", label: t("nav.method"), icon: "?" },
];

const expertNavigation: Array<{
  activeSection?: PublicSection;
  href: string;
  label: ReturnType<typeof t>;
}> = [
  { activeSection: "expert", href: "/expert", label: t("nav.expert") },
  { activeSection: "learning", href: "/apprentissage", label: t("nav.learning") },
  { activeSection: "laboratory", href: "/laboratoire", label: t("nav.laboratory") },
  { href: "/expert#donnees", label: t("nav.expert.data") },
  { href: "/expert#modeles", label: t("nav.expert.models") },
  { href: "/expert#simulations", label: t("nav.expert.simulations") },
  { href: "/expert#couts", label: t("nav.expert.costs") },
  { href: "/expert#systeme", label: t("nav.expert.system") },
];

export function ExperienceShell({
  active,
  children,
}: {
  active: PublicSection;
  children: ReactNode;
}) {
  const [glossaryOpen, setGlossaryOpen] = useState(false);
  const glossaryRef = useRef<HTMLElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const isExpertNavigationActive =
    active === "expert" || active === "learning" || active === "laboratory";

  useEffect(() => {
    if (!glossaryOpen) return;
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const dialog = glossaryRef.current;
    const focusable = dialog?.querySelectorAll<HTMLElement>(
      "button, summary, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    focusable?.[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setGlossaryOpen(false);
        return;
      }
      if (event.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [glossaryOpen]);

  return (
    <ViewModeProvider>
      <div className="app-shell">
        <a className="skip-link" href="#contenu-principal">
          Aller au contenu principal
        </a>
        <aside className="sidebar">
          <Link className="brand" href="/robin-live" aria-label={t("brand.name")}>
            <span className="brand-mark" aria-hidden="true">R</span>
            <span>
              <strong>{t("brand.name")}</strong>
              <small>{t("brand.tagline")}</small>
            </span>
          </Link>
          <div className="observatory-state">
            <span className="live-dot" aria-hidden="true" />
            <span>
              <strong>{t("home.observatory")}</strong>
              <small>{operationalEvidence.fixtures} rencontres suivies</small>
            </span>
          </div>
          <nav className="side-nav" aria-label="Navigation principale">
            {publicNavigation.map((item) => (
              <Link
                aria-current={active === item.key ? "page" : undefined}
                className={active === item.key ? "active" : ""}
                href={item.href}
                key={item.key}
              >
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
              </Link>
            ))}
            <details className="expert-nav" open={isExpertNavigationActive}>
              <summary className={isExpertNavigationActive ? "active" : ""}>
                <span aria-hidden="true">⌘</span>
                {t("nav.expert")}
              </summary>
              <div>
                {expertNavigation.map((item) => (
                  <Link
                    aria-current={
                      item.activeSection === active ? "page" : undefined
                    }
                    href={item.href}
                    key={item.href}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </details>
          </nav>
          <div className="sidebar-footer">
            <StatusBadge value="PRODUCTION_LOCKED" />
            <small>{t("home.noBet")}</small>
          </div>
        </aside>

        <div className="app-main">
          <header className="topbar">
            <Link
              aria-label={t("brand.name")}
              className="mobile-logo"
              href="/robin-live"
            >
              <span>R</span>
              Robin
            </Link>
            <p>
              {t("common.updated")}{" "}
              <time dateTime={operationalEvidence.generatedAt}>
                {formatDateTime(operationalEvidence.generatedAt, true)}
              </time>
              {" · "}
              <StatusBadge value={operationalEvidence.freshness.status} />
            </p>
            <div className="topbar-actions">
              <button
                aria-label={t("glossary.title")}
                className="glossary-button"
                onClick={() => setGlossaryOpen(true)}
                type="button"
              >
                <span aria-hidden="true">?</span>
                <span>{t("glossary.title")}</span>
              </button>
              <ViewModeSwitch />
            </div>
          </header>

          <main id="contenu-principal" className="content" tabIndex={-1}>
            {children}
          </main>

          <footer className="site-footer">
            <p>{t("footer.disclaimer")}</p>
            <p>{t("footer.timezone")}</p>
          </footer>
        </div>

        <nav className="mobile-nav" aria-label="Navigation mobile">
          {publicNavigation.map((item) => (
            <Link
              aria-current={active === item.key ? "page" : undefined}
              className={active === item.key ? "active" : ""}
              href={item.href}
              key={item.key}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </Link>
          ))}
          <Link
            aria-current={isExpertNavigationActive ? "page" : undefined}
            className={isExpertNavigationActive ? "active" : ""}
            href="/expert"
          >
            <span aria-hidden="true">⌘</span>
            Expert
          </Link>
        </nav>

        {glossaryOpen ? (
          <div
            className="drawer-backdrop"
            onMouseDown={(event) => {
              if (event.currentTarget === event.target) setGlossaryOpen(false);
            }}
          >
            <aside
              aria-label={t("glossary.title")}
              aria-modal="true"
              className="glossary-drawer"
              ref={glossaryRef}
              role="dialog"
            >
              <div className="drawer-head">
                <div>
                  <p className="eyebrow">{t("glossary.simple")}</p>
                  <h2>{t("glossary.title")}</h2>
                </div>
                <button
                  aria-label={t("action.close")}
                  onClick={() => setGlossaryOpen(false)}
                  type="button"
                >
                  ×
                </button>
              </div>
              <div className="glossary-list">
                {glossary.map((entry) => (
                  <details key={entry.term}>
                    <summary>
                      <strong>{entry.publicName}</strong>
                      <ExpertOnly>
                        <span>{entry.term}</span>
                      </ExpertOnly>
                    </summary>
                    <p>{entry.simple}</p>
                    <ExpertOnly>
                      <small>{entry.expert}</small>
                    </ExpertOnly>
                  </details>
                ))}
              </div>
            </aside>
          </div>
        ) : null}
      </div>
    </ViewModeProvider>
  );
}
