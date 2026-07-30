import {
  EvidenceChartEmptyState,
  EvidenceChartFrame,
  EvidenceFallbackTable,
  HistoricalMatchLink,
} from "./historical-evidence-chart-shell";
import {
  buildDivergingBars,
  evidenceChartPalette,
  formatChartInteger,
  formatChartPercent,
  formatSignedUnits,
  historicalMatchAccessibleLabel,
  historicalMatchHref,
  historicalMatchPublicLabel,
  type HistoricalMatchReference,
} from "./historical-evidence-chart-utils";

export type HypothesisFoldEvidence = HistoricalMatchReference & {
  fold: number;
  label?: string;
  matches: number;
  positive?: boolean;
  profitUnits: number;
  roi: number;
  testEnd?: string;
  testStart?: string;
  trainEnd?: string;
  trainStart?: string;
};

export type HypothesisFoldValidationProps = {
  folds: readonly HypothesisFoldEvidence[];
  interpretation?: "chronological-periods" | "validation-folds";
  sourceNote?: string;
  subtitle?: string;
  title?: string;
};

function foldLabel(fold: HypothesisFoldEvidence): string {
  return fold.label ?? `Fold ${fold.fold}`;
}

function periodLabel(start?: string, end?: string): string {
  if (start && end) return `${start} → ${end}`;
  return start ?? end ?? "Non disponible";
}

export function HypothesisFoldValidation({
  folds,
  interpretation = "validation-folds",
  sourceNote,
  subtitle,
  title,
}: HypothesisFoldValidationProps) {
  const isPeriodBreakdown = interpretation === "chronological-periods";
  const resolvedTitle =
    title ??
    (isPeriodBreakdown
      ? "Résultats par période chronologique"
      : "Validation chronologique par période");
  const resolvedSubtitle =
    subtitle ??
    (isPeriodBreakdown
      ? "ROI des groupes temporels documentés dans l’index d’appartenance."
      : "ROI de chaque fenêtre de test chronologique ; aucune période future n’alimente son apprentissage.");
  if (folds.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle={
          isPeriodBreakdown
            ? "Aucune période chronologique détaillée n’est disponible pour cette hypothèse."
            : "Aucune période de validation chronologique n’est disponible pour cette hypothèse."
        }
        title={resolvedTitle}
      />
    );
  }

  const orderedFolds = [...folds].sort((left, right) => left.fold - right.fold);
  const geometry = buildDivergingBars(
    orderedFolds.map((fold) => fold.roi),
    { left: 178, right: 72, rowGap: 42, top: 24, width: 760 },
  );
  const positiveCount = orderedFolds.filter(
    (fold) => fold.positive ?? fold.profitUnits > 0,
  ).length;
  const totalMatches = orderedFolds.reduce(
    (sum, fold) => sum + Math.max(0, fold.matches),
    0,
  );
  const totalProfit = orderedFolds.reduce(
    (sum, fold) => sum + fold.profitUnits,
    0,
  );
  const summary = isPeriodBreakdown
    ? `${positiveCount}/${orderedFolds.length} périodes chronologiques présentent un profit positif. Elles regroupent ${formatChartInteger(totalMatches)} observations pour un profit cumulé de ${formatSignedUnits(totalProfit)} ; elles décrivent l’historique et ne remplacent pas la validation agrégée du rapport.`
    : `${positiveCount}/${orderedFolds.length} périodes de validation présentent un profit positif. Elles regroupent ${formatChartInteger(totalMatches)} observations pour un profit cumulé de ${formatSignedUnits(totalProfit)} ; chaque barre représente uniquement sa fenêtre de test.`;

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption={
            isPeriodBreakdown
              ? "Résultats exacts de chaque période chronologique documentée."
              : "Résultats exacts de chaque fenêtre de validation chronologique."
          }
          columns={
            isPeriodBreakdown
              ? [
                  "Période",
                  "Match de référence",
                  "Observations",
                  "Profit",
                  "ROI",
                  "Signe",
                ]
              : [
                  "Période",
                  "Match de référence",
                  "Apprentissage",
                  "Test",
                  "Observations",
                  "Profit",
                  "ROI",
                  "Signe",
                ]
          }
          rows={orderedFolds.map((fold, index) => {
            const positive = fold.positive ?? fold.profitUnits > 0;
            return {
              cells: isPeriodBreakdown
                ? [
                    foldLabel(fold),
                    <HistoricalMatchLink
                      key={fold.matchHref ?? `match-${index}`}
                      reference={fold}
                    >
                      {historicalMatchPublicLabel(fold)}
                    </HistoricalMatchLink>,
                    formatChartInteger(fold.matches),
                    formatSignedUnits(fold.profitUnits),
                    formatChartPercent(fold.roi),
                    positive ? "Positif" : "Négatif ou nul",
                  ]
                : [
                    foldLabel(fold),
                    <HistoricalMatchLink
                      key={fold.matchHref ?? `match-${index}`}
                      reference={fold}
                    >
                      {historicalMatchPublicLabel(fold)}
                    </HistoricalMatchLink>,
                    periodLabel(fold.trainStart, fold.trainEnd),
                    periodLabel(fold.testStart, fold.testEnd),
                    formatChartInteger(fold.matches),
                    formatSignedUnits(fold.profitUnits),
                    formatChartPercent(fold.roi),
                    positive ? "Positif" : "Négatif ou nul",
                  ],
              key: `${fold.fold}-${index}`,
            };
          })}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: isPeriodBreakdown
            ? "Période au profit positif"
            : "Période de validation au profit positif",
        },
        {
          color: evidenceChartPalette.orange,
          dashed: true,
          label: isPeriodBreakdown
            ? "Période au profit négatif ou nul"
            : "Période de validation au profit négatif ou nul",
          open: true,
        },
        {
          color: evidenceChartPalette.zero,
          label: "ROI nul",
          open: true,
        },
      ]}
      sourceNote={sourceNote}
      subtitle={resolvedSubtitle}
      summary={summary}
      title={resolvedTitle}
    >
      <svg
        aria-label={summary}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        style={{ display: "block", height: "auto", maxWidth: "100%", width: "100%" }}
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
      >
        <title>{resolvedTitle}</title>
        <desc>{summary}</desc>
        <rect
          fill={evidenceChartPalette.paper}
          height={geometry.height}
          width={geometry.width}
          x={0}
          y={0}
        />
        <line
          stroke={evidenceChartPalette.zero}
          strokeWidth={1.5}
          x1={geometry.zeroX}
          x2={geometry.zeroX}
          y1={18}
          y2={geometry.height - 30}
        />
        <text
          fill={evidenceChartPalette.muted}
          fontSize={10}
          textAnchor="middle"
          x={geometry.zeroX}
          y={geometry.height - 12}
        >
          ROI 0 %
        </text>

        {geometry.bars.map((bar) => {
          const fold = orderedFolds[bar.index];
          if (!fold) return null;
          const positive = fold.positive ?? fold.profitUnits > 0;
          const href = historicalMatchHref(fold);
          const mark = (
            <rect
              fill={
                positive
                  ? evidenceChartPalette.blue
                  : evidenceChartPalette.orangeOpen
              }
              height={20}
              stroke={
                positive
                  ? evidenceChartPalette.blue
                  : evidenceChartPalette.orange
              }
              strokeDasharray={positive ? undefined : "5 3"}
              strokeWidth={2}
              width={Math.max(1, bar.width)}
              x={bar.x}
              y={bar.y}
            >
              <title>
                {isPeriodBreakdown
                  ? `${foldLabel(fold)} : ROI ${formatChartPercent(fold.roi)}, profit ${formatSignedUnits(fold.profitUnits)}, ${formatChartInteger(fold.matches)} observations, référence ${historicalMatchAccessibleLabel(fold)}`
                  : `${foldLabel(fold)} : ROI ${formatChartPercent(fold.roi)}, profit ${formatSignedUnits(fold.profitUnits)}, ${formatChartInteger(fold.matches)} observations, test ${periodLabel(fold.testStart, fold.testEnd)}, référence ${historicalMatchAccessibleLabel(fold)}`}
              </title>
            </rect>
          );

          return (
            <g key={`${fold.fold}-${bar.index}`}>
              <text
                fill={evidenceChartPalette.ink}
                fontSize={12}
                textAnchor="end"
                x={168}
                y={bar.y + 14}
              >
                {foldLabel(fold)}
              </text>
              {href ? (
                <a
                  aria-label={`Ouvrir le match de référence ${historicalMatchAccessibleLabel(
                    fold,
                    `de ${foldLabel(fold)}`,
                  )}`}
                  href={href}
                >
                  {mark}
                </a>
              ) : (
                mark
              )}
              <text
                fill={evidenceChartPalette.ink}
                fontSize={11}
                textAnchor="end"
                x={geometry.width - 8}
                y={bar.y + 14}
              >
                {formatChartPercent(fold.roi)}
              </text>
            </g>
          );
        })}
      </svg>
    </EvidenceChartFrame>
  );
}
