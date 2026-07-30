import {
  EvidenceChartEmptyState,
  EvidenceChartFrame,
  EvidenceFallbackTable,
  HistoricalMatchLink,
} from "./historical-evidence-chart-shell";
import {
  evidenceChartPalette,
  formatChartInteger,
  formatChartNumber,
  formatChartPercent,
  formatSignedUnits,
  historicalMatchAccessibleLabel,
  historicalMatchHref,
  historicalMatchPublicLabel,
  makeEvenTicks,
  scaleLinear,
  type HistoricalMatchReference,
} from "./historical-evidence-chart-utils";

export type HypothesisOddsBin = HistoricalMatchReference & {
  label?: string;
  matches: number;
  maximumOdds: number;
  minimumOdds: number;
  profitUnits?: number;
  wins?: number;
};

export type HypothesisOddsDistributionProps = {
  bins: readonly HypothesisOddsBin[];
  sourceNote?: string;
  subtitle?: string;
  title?: string;
};

const width = 760;
const height = 300;
const padding = { bottom: 58, left: 58, right: 24, top: 24 } as const;

function oddsBinLabel(bin: HypothesisOddsBin): string {
  if (bin.label) return bin.label;
  return `${formatChartNumber(bin.minimumOdds)}–${formatChartNumber(bin.maximumOdds)}`;
}

export function HypothesisOddsDistribution({
  bins,
  sourceNote,
  subtitle = "Nombre de matchs éligibles par intervalle de cote observée.",
  title = "Distribution des cotes historiques",
}: HypothesisOddsDistributionProps) {
  if (bins.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle="Aucun intervalle de cote n’est disponible pour cette hypothèse."
        title={title}
      />
    );
  }

  const orderedBins = [...bins].sort(
    (left, right) => left.minimumOdds - right.minimumOdds,
  );
  const maximumMatches = Math.max(
    1,
    ...orderedBins.map((bin) => Math.max(0, bin.matches)),
  );
  const totalMatches = orderedBins.reduce(
    (sum, bin) => sum + Math.max(0, bin.matches),
    0,
  );
  const modalBin = orderedBins.reduce((current, bin) =>
    bin.matches > current.matches ? bin : current,
  );
  const plotWidth = width - padding.left - padding.right;
  const slotWidth = plotWidth / Math.max(1, orderedBins.length);
  const barWidth = Math.max(2, slotWidth * 0.72);
  const labelStep = Math.max(1, Math.ceil(orderedBins.length / 8));
  const ticks = makeEvenTicks(0, maximumMatches, 5);
  const summary = `${formatChartInteger(totalMatches)} observations sont réparties dans ${formatChartInteger(orderedBins.length)} intervalle${orderedBins.length > 1 ? "s" : ""}. L’intervalle le plus fréquent est ${oddsBinLabel(modalBin)} avec ${formatChartInteger(modalBin.matches)} match${modalBin.matches > 1 ? "s" : ""}.`;

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption="Effectifs, résultats et profit par intervalle de cote."
          columns={[
            "Intervalle",
            "Match de référence",
            "Observations",
            "Victoires",
            "Taux de réussite",
            "Profit",
          ]}
          rows={orderedBins.map((bin, index) => ({
            cells: [
              oddsBinLabel(bin),
              <HistoricalMatchLink
                key={bin.matchHref ?? `match-${index}`}
                reference={bin}
              >
                {historicalMatchPublicLabel(bin)}
              </HistoricalMatchLink>,
              formatChartInteger(bin.matches),
              bin.wins == null
                ? "Non disponible"
                : formatChartInteger(bin.wins),
              bin.wins == null || bin.matches <= 0
                ? "Non disponible"
                : formatChartPercent(bin.wins / bin.matches),
              bin.profitUnits == null
                ? "Non disponible"
                : formatSignedUnits(bin.profitUnits),
            ],
            key: `${bin.minimumOdds}-${bin.maximumOdds}-${index}`,
          }))}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: "Nombre de matchs",
        },
        {
          color: evidenceChartPalette.zero,
          label: "Base zéro",
          open: true,
        },
      ]}
      sourceNote={sourceNote}
      subtitle={subtitle}
      summary={summary}
      title={title}
    >
      <svg
        aria-label={summary}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        style={{ display: "block", height: "auto", maxWidth: "100%", width: "100%" }}
        viewBox={`0 0 ${width} ${height}`}
      >
        <title>{title}</title>
        <desc>{summary}</desc>
        <rect
          fill={evidenceChartPalette.paper}
          height={height}
          width={width}
          x={0}
          y={0}
        />
        {ticks.map((tick) => {
          const y = scaleLinear(
            tick,
            0,
            maximumMatches,
            height - padding.bottom,
            padding.top,
          );
          return (
            <g key={tick}>
              <line
                stroke={evidenceChartPalette.grid}
                strokeWidth={1}
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
              />
              <text
                fill={evidenceChartPalette.muted}
                fontSize={10}
                textAnchor="end"
                x={padding.left - 8}
                y={y + 4}
              >
                {formatChartInteger(tick)}
              </text>
            </g>
          );
        })}

        {orderedBins.map((bin, index) => {
          const x = padding.left + index * slotWidth + (slotWidth - barWidth) / 2;
          const y = scaleLinear(
            Math.max(0, bin.matches),
            0,
            maximumMatches,
            height - padding.bottom,
            padding.top,
          );
          const barHeight = height - padding.bottom - y;
          const href = historicalMatchHref(bin);
          const tooltipParts = [
            `${oddsBinLabel(bin)} : ${formatChartInteger(bin.matches)} observations`,
            bin.wins == null
              ? null
              : `${formatChartInteger(bin.wins)} victoires`,
            bin.wins == null || bin.matches <= 0
              ? null
              : `réussite ${formatChartPercent(bin.wins / bin.matches)}`,
            bin.profitUnits == null
              ? null
              : `profit ${formatSignedUnits(bin.profitUnits)}`,
            href
              ? `référence ${historicalMatchAccessibleLabel(bin)}`
              : null,
          ].filter((part): part is string => part !== null);
          const mark = (
            <rect
              fill={evidenceChartPalette.blue}
              height={Math.max(0, barHeight)}
              stroke={evidenceChartPalette.blue}
              strokeWidth={1}
              width={barWidth}
              x={x}
              y={y}
            >
              <title>{tooltipParts.join(", ")}</title>
            </rect>
          );

          return (
            <g key={`${bin.minimumOdds}-${bin.maximumOdds}-${index}`}>
              {href ? (
                <a
                  aria-label={`Ouvrir le match de référence ${historicalMatchAccessibleLabel(
                    bin,
                    `de l’intervalle ${oddsBinLabel(bin)}`,
                  )}`}
                  href={href}
                >
                  {mark}
                </a>
              ) : (
                mark
              )}
              {index % labelStep === 0 || index === orderedBins.length - 1 ? (
                <text
                  fill={evidenceChartPalette.muted}
                  fontSize={10}
                  textAnchor="middle"
                  x={x + barWidth / 2}
                  y={height - padding.bottom + 18}
                >
                  {oddsBinLabel(bin)}
                </text>
              ) : null}
            </g>
          );
        })}
        <text
          fill={evidenceChartPalette.muted}
          fontSize={10}
          textAnchor="middle"
          x={(padding.left + width - padding.right) / 2}
          y={height - 8}
        >
          Cote observée
        </text>
      </svg>
    </EvidenceChartFrame>
  );
}
