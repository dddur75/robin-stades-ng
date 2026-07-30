import Link from "next/link";
import type { ReactNode } from "react";

import {
  familyDisplayName,
  familySlug,
  hypothesisTag,
  scientificStatusLabel,
  type RankingEntry,
} from "../../lib/hypothesis-universe";
import { formatNumber, formatPercent } from "../../i18n";
import { ExpertOnly } from "../common/view-mode";

export function HypothesisBreadcrumbs({
  items,
}: {
  items: Array<{ href?: string; label: string }>;
}) {
  return (
    <nav aria-label="Fil d’Ariane" className="hu-breadcrumbs">
      <ol>
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`}>
            {item.href ? <Link href={item.href}>{item.label}</Link> : <span aria-current="page">{item.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function HypothesisSubnav() {
  const links = [
    ["Univers", "/hypotheses"],
    ["Familles", "/hypotheses/familles"],
    ["Arbres", "/hypotheses/arbres"],
    ["Classements", "/hypotheses/classements"],
    ["Observations", "/hypotheses/observations"],
    ["Longue traîne", "/hypotheses/longue-traine"],
  ] as const;
  return (
    <nav aria-label="Navigation de l’univers des hypothèses" className="hu-subnav">
      {links.map(([label, href]) => (
        <Link href={href} key={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

export function ScientificStatusBadge({
  status,
}: {
  status: string;
}) {
  const normalized = status.toLocaleUpperCase("fr-FR");
  const definition = hypothesisTag(`status:${status}`);
  const tone =
    normalized.includes("VALIDATED") || normalized === "READY"
      ? "validated"
      : normalized.includes("BLOCK") || normalized.includes("REJECT")
        ? "blocked"
        : normalized.includes("PROSPECT")
          ? "prospective"
          : normalized.includes("LONG")
            ? "long-tail"
            : normalized.includes("DEFER") || normalized.includes("PRUN")
              ? "deferred"
              : "exploratory";
  return (
    <span
      className={`hu-status hu-status-${tone}`}
      data-semantic-role={definition?.semantic_role}
      data-tag-id={definition?.tag_id}
      title={definition?.description_fr}
    >
      <span aria-hidden="true" />
      {scientificStatusLabel(status)}
    </span>
  );
}

export function TagChip({
  children,
  kind = "neutral",
  tagId,
}: {
  children: ReactNode;
  kind?: "family" | "neutral" | "science" | "value";
  tagId?: string;
}) {
  const definition = tagId ? hypothesisTag(tagId) : undefined;
  return (
    <span
      className={`hu-tag hu-tag-${kind}`}
      data-parent-tag={definition?.parent_tag ?? undefined}
      data-semantic-role={definition?.semantic_role}
      data-tag-id={definition?.tag_id}
      title={definition?.description_fr}
    >
      {children}
    </span>
  );
}

export function UniverseMetric({
  detail,
  label,
  tone = "neutral",
  value,
}: {
  detail?: string;
  label: string;
  tone?: "blue" | "coral" | "gold" | "neutral" | "teal" | "violet";
  value: number | string;
}) {
  return (
    <article className={`hu-metric hu-metric-${tone}`}>
      <p>{label}</p>
      <strong>{typeof value === "number" ? formatNumber(value) : value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}

export function UniverseSectionHeading({
  action,
  eyebrow,
  subtitle,
  title,
}: {
  action?: ReactNode;
  eyebrow?: string;
  subtitle?: string;
  title: string;
}) {
  return (
    <div className="hu-section-heading">
      <div>
        {eyebrow ? <p className="hu-kicker">{eyebrow}</p> : null}
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function RankingCard({
  entry,
  showRank = true,
}: {
  entry: RankingEntry;
  showRank?: boolean;
}) {
  return (
    <article className="hu-ranking-card">
      <div className="hu-ranking-card-head">
        {showRank ? <span className="hu-rank">#{entry.rank}</span> : null}
        <ScientificStatusBadge status={entry.status} />
      </div>
      <h3>{entry.hypothesis_id}</h3>
      <p>{entry.label_fr}</p>
      <dl>
        <div>
          <dt>Championnat</dt>
          <dd>{entry.competition ?? "Tous"}</dd>
        </div>
        <div>
          <dt>Famille</dt>
          <dd>
                <Link href={`/hypotheses/familles/${familySlug(entry.family)}`}>
              {familyDisplayName(entry.family)}
            </Link>
          </dd>
        </div>
        <div>
          <dt>Matchs observés</dt>
          <dd>
            {entry.historical_support == null
              ? "Non disponible"
              : formatNumber(entry.historical_support)}
          </dd>
        </div>
        <div>
          <dt>Résultat historique brut</dt>
          <dd>{formatPercent(entry.historical_roi)}</dd>
        </div>
      </dl>
      <Link className="hu-text-link" href={`/hypotheses/${entry.hypothesis_id}`}>
        Ouvrir la fiche
        <span aria-hidden="true"> →</span>
      </Link>
    </article>
  );
}

export function HonestEmptyState({
  children,
  icon = "○",
  title,
}: {
  children: ReactNode;
  icon?: string;
  title: string;
}) {
  return (
    <div className="hu-empty">
      <span aria-hidden="true">{icon}</span>
      <div>
        <h3>{title}</h3>
        <p>{children}</p>
      </div>
    </div>
  );
}

export function MetricExplainer({
  expert,
  name,
  simple,
}: {
  expert?: string;
  name: string;
  simple: string;
}) {
  return (
    <details className="hu-metric-explainer">
      <summary>
        <span>{name}</span>
        <small>Définition</small>
      </summary>
      <p>{simple}</p>
      {expert ? (
        <ExpertOnly>
          <small>{expert}</small>
        </ExpertOnly>
      ) : null}
    </details>
  );
}
