import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import {
  evidenceChartPalette,
  historicalMatchHref,
  type HistoricalMatchReference,
} from "./historical-evidence-chart-utils";

const figureStyle: CSSProperties = {
  display: "grid",
  gap: "0.8rem",
  margin: 0,
  maxWidth: "100%",
  minWidth: 0,
};

const headerStyle: CSSProperties = {
  display: "grid",
  gap: "0.25rem",
};

const titleStyle: CSSProperties = {
  color: evidenceChartPalette.ink,
  fontSize: "1rem",
  lineHeight: 1.3,
  margin: 0,
};

const subtitleStyle: CSSProperties = {
  color: evidenceChartPalette.muted,
  fontSize: "0.8rem",
  lineHeight: 1.5,
  margin: 0,
};

const legendStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  flexWrap: "wrap",
  gap: "0.55rem 1rem",
  listStyle: "none",
  margin: 0,
  padding: 0,
};

const summaryStyle: CSSProperties = {
  borderLeft: `3px solid ${evidenceChartPalette.blue}`,
  color: evidenceChartPalette.ink,
  fontSize: "0.82rem",
  lineHeight: 1.55,
  margin: 0,
  padding: "0.45rem 0.7rem",
};

const tableWrapperStyle: CSSProperties = {
  maxWidth: "100%",
  overflowX: "auto",
};

const tableStyle: CSSProperties = {
  borderCollapse: "collapse",
  fontSize: "0.75rem",
  minWidth: "34rem",
  width: "100%",
};

const cellStyle: CSSProperties = {
  borderBottom: `1px solid ${evidenceChartPalette.grid}`,
  padding: "0.5rem 0.6rem",
  textAlign: "left",
  verticalAlign: "top",
};

export type EvidenceLegendItem = {
  color: string;
  dashed?: boolean;
  label: string;
  open?: boolean;
};

export function EvidenceChartFrame({
  children,
  fallback,
  legend,
  sourceNote,
  subtitle,
  summary,
  title,
}: {
  children: ReactNode;
  fallback: ReactNode;
  legend: readonly EvidenceLegendItem[];
  sourceNote?: string;
  subtitle: string;
  summary: string;
  title: string;
}) {
  return (
    <figure style={figureStyle}>
      <figcaption style={headerStyle}>
        <h3 style={titleStyle}>{title}</h3>
        <p style={subtitleStyle}>{subtitle}</p>
      </figcaption>
      <ul aria-label="Légende" style={legendStyle}>
        {legend.map((item) => (
          <li
            key={item.label}
            style={{
              alignItems: "center",
              color: evidenceChartPalette.muted,
              display: "inline-flex",
              fontSize: "0.72rem",
              gap: "0.4rem",
            }}
          >
            <span
              aria-hidden="true"
              style={{
                background: item.open ? evidenceChartPalette.paper : item.color,
                border: `2px ${item.dashed ? "dashed" : "solid"} ${item.color}`,
                display: "inline-block",
                height: "0.65rem",
                width: "1.25rem",
              }}
            />
            {item.label}
          </li>
        ))}
      </ul>
      {children}
      <p style={summaryStyle}>{summary}</p>
      {sourceNote ? <p style={subtitleStyle}>{sourceNote}</p> : null}
      {fallback}
    </figure>
  );
}

export function EvidenceChartEmptyState({
  subtitle,
  title,
}: {
  subtitle: string;
  title: string;
}) {
  return (
    <section
      aria-label={title}
      style={{
        border: `1px solid ${evidenceChartPalette.grid}`,
        color: evidenceChartPalette.muted,
        padding: "1rem",
      }}
    >
      <h3 style={titleStyle}>{title}</h3>
      <p style={subtitleStyle}>{subtitle}</p>
    </section>
  );
}

export function EvidenceFallbackTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: readonly string[];
  rows: ReadonlyArray<{ cells: readonly ReactNode[]; key: string }>;
}) {
  return (
    <details>
      <summary
        style={{
          color: evidenceChartPalette.ink,
          cursor: "pointer",
          fontSize: "0.78rem",
          fontWeight: 650,
        }}
      >
        Données accessibles du graphique
      </summary>
      <div style={tableWrapperStyle} tabIndex={0}>
        <table style={tableStyle}>
          <caption
            style={{
              color: evidenceChartPalette.muted,
              padding: "0.55rem 0",
              textAlign: "left",
            }}
          >
            {caption}
          </caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col" style={cellStyle}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                {row.cells.map((cell, index) => (
                  <td key={`${row.key}-${columns[index] ?? index}`} style={cellStyle}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function HistoricalMatchLink({
  children,
  reference,
}: {
  children: ReactNode;
  reference: HistoricalMatchReference;
}) {
  const href = historicalMatchHref(reference);
  return href ? <Link href={href}>{children}</Link> : children;
}
