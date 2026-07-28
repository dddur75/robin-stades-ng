import Link from "next/link";
import type { ReactNode } from "react";

import { statusPresentation } from "../../i18n/status-translations";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-subtitle">{subtitle}</p>
      </div>
      {children}
    </header>
  );
}

export function SectionHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        <h2>{title}</h2>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = "neutral",
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "green" | "blue" | "orange" | "violet";
  icon?: string;
}) {
  return (
    <article className={`metric-card tone-${tone}`}>
      <div className="metric-card-label">
        {icon ? <span aria-hidden="true">{icon}</span> : null}
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

export function StatusBadge({
  value,
  showTechnical = false,
}: {
  value: string;
  showTechnical?: boolean;
}) {
  const status = statusPresentation(value);
  return (
    <span
      className={`status-badge status-${status.tone}`}
      title={`${status.long}${status.action ? ` ${status.action}` : ""}`}
      aria-label={`${status.short}. ${status.long}`}
    >
      <span aria-hidden="true">{status.icon}</span>
      <span>{status.short}</span>
      {showTechnical ? <code>{value}</code> : null}
    </span>
  );
}

export function ProgressBar({
  value,
  label,
}: {
  value: number;
  label: string;
}) {
  const bounded = Math.max(0, Math.min(value, 1));
  return (
    <div className="progress-block">
      <div>
        <span>{label}</span>
        <strong>{new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 }).format(bounded)}</strong>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(bounded * 100)}
      >
        <i style={{ width: `${bounded * 100}%` }} />
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state-mark" aria-hidden="true">○</span>
      <div>
        <h3>{title}</h3>
        <p>{text}</p>
        {action}
      </div>
    </div>
  );
}

export function InlineLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <Link className="inline-link" href={href}>
      {children}
      <span aria-hidden="true"> →</span>
    </Link>
  );
}

export function EvidenceNote({ children }: { children: ReactNode }) {
  return (
    <aside className="evidence-note">
      <span aria-hidden="true">i</span>
      <p>{children}</p>
    </aside>
  );
}

export function TechnicalList({
  rows,
}: {
  rows: Array<{ label: string; value: ReactNode }>;
}) {
  return (
    <dl className="technical-list">
      {rows.map((row) => (
        <div key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
