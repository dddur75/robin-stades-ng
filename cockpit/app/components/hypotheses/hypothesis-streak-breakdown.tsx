import type { CSSProperties } from "react";

import {
  EvidenceChartEmptyState,
  EvidenceChartFrame,
  EvidenceFallbackTable,
} from "./historical-evidence-chart-shell";
import {
  evidenceChartPalette,
  formatChartInteger,
} from "./historical-evidence-chart-utils";

export type HypothesisStreakRun = Readonly<{
  endOccurrenceIndex: number;
  length: number;
  outcome: "won" | "lost";
  startOccurrenceIndex: number;
}>;

export type HypothesisStreakSummary = Readonly<{
  currentLength: number;
  longestLength: number;
  runCount: number;
}>;

export type HypothesisStreakBreakdownProps = Readonly<{
  losing: HypothesisStreakSummary;
  runs: readonly HypothesisStreakRun[];
  sourceNote?: string;
  winning: HypothesisStreakSummary;
}>;

const trackStyle: CSSProperties = {
  background: evidenceChartPalette.grid,
  borderRadius: "999px",
  height: "0.75rem",
  overflow: "hidden",
};

function StreakMetric({
  label,
  maximum,
  summary,
  tone,
}: {
  label: string;
  maximum: number;
  summary: HypothesisStreakSummary;
  tone: string;
}) {
  const width =
    maximum <= 0
      ? 0
      : Math.max(
          0,
          Math.min(100, (summary.longestLength / maximum) * 100),
        );
  return (
    <article
      style={{
        border: `1px solid ${evidenceChartPalette.grid}`,
        display: "grid",
        gap: "0.6rem",
        minWidth: 0,
        padding: "0.9rem",
      }}
    >
      <div>
        <strong>{label}</strong>
        <p style={{ color: evidenceChartPalette.muted, margin: "0.2rem 0 0" }}>
          {formatChartInteger(summary.runCount)} série
          {summary.runCount > 1 ? "s" : ""} · record{" "}
          {formatChartInteger(summary.longestLength)} · série actuelle{" "}
          {formatChartInteger(summary.currentLength)}
        </p>
      </div>
      <div
        aria-label={`${label} : record de ${formatChartInteger(summary.longestLength)} matchs`}
        role="img"
        style={trackStyle}
      >
        <span
          style={{
            background: tone,
            display: "block",
            height: "100%",
            width: `${width}%`,
          }}
        />
      </div>
    </article>
  );
}

export function HypothesisStreakBreakdown({
  losing,
  runs,
  sourceNote,
  winning,
}: HypothesisStreakBreakdownProps) {
  if (runs.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle="Aucune séquence gagnante ou perdante n’est disponible pour cette hypothèse."
        title="Séries gagnantes et perdantes"
      />
    );
  }

  const maximum = Math.max(
    1,
    winning.longestLength,
    losing.longestLength,
  );
  const summary =
    `La plus longue série gagnante compte ${formatChartInteger(
      winning.longestLength,
    )} match${winning.longestLength > 1 ? "s" : ""}; ` +
    `la plus longue série perdante en compte ${formatChartInteger(
      losing.longestLength,
    )}. Ces séquences décrivent l’historique et ne prédisent pas la suite.`;

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption="Toutes les séries consécutives reconstruites dans l’ordre historique."
          columns={[
            "Issue",
            "Longueur",
            "Première occurrence",
            "Dernière occurrence",
          ]}
          rows={runs.map((run, index) => ({
            cells: [
              run.outcome === "won" ? "Gagnée" : "Perdue",
              formatChartInteger(run.length),
              formatChartInteger(run.startOccurrenceIndex),
              formatChartInteger(run.endOccurrenceIndex),
            ],
            key: `${run.outcome}-${run.startOccurrenceIndex}-${index}`,
          }))}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: "Séries gagnantes",
        },
        {
          color: evidenceChartPalette.orange,
          label: "Séries perdantes",
        },
      ]}
      sourceNote={sourceNote}
      subtitle="Longueur des séquences consécutives, sans code de casino ni promesse de gain."
      summary={summary}
      title="Séries gagnantes et perdantes"
    >
      <div
        style={{
          display: "grid",
          gap: "0.75rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 15rem), 1fr))",
        }}
      >
        <StreakMetric
          label="Séries gagnantes"
          maximum={maximum}
          summary={winning}
          tone={evidenceChartPalette.blue}
        />
        <StreakMetric
          label="Séries perdantes"
          maximum={maximum}
          summary={losing}
          tone={evidenceChartPalette.orange}
        />
      </div>
    </EvidenceChartFrame>
  );
}
