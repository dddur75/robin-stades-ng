import {
  EvidenceChartEmptyState,
  EvidenceChartFrame,
  EvidenceFallbackTable,
  HistoricalMatchLink,
} from "./historical-evidence-chart-shell";
import {
  computeConcentrationShares,
  evidenceChartPalette,
  formatChartInteger,
  formatChartPercent,
  formatSignedUnits,
  historicalMatchAccessibleLabel,
  historicalMatchHref,
  historicalMatchPublicLabel,
  type HistoricalMatchReference,
} from "./historical-evidence-chart-utils";

export type HypothesisTeamConcentrationItem = HistoricalMatchReference & {
  losses: number;
  matches: number;
  profitUnits: number;
  share?: number;
  team: string;
  voids: number;
  wins: number;
};

export type HypothesisTeamConcentrationProps = {
  items: readonly HypothesisTeamConcentrationItem[];
  sourceNote?: string;
  subtitle?: string;
  title?: string;
  topN?: number;
  totalMatches?: number;
};

function shortTeamName(team: string): string {
  return team.length > 27 ? `${team.slice(0, 25)}…` : team;
}

export function HypothesisTeamConcentration({
  items,
  sourceNote,
  subtitle = "Part des observations historiques associées aux équipes les plus représentées.",
  title = "Concentration des observations par équipe",
  topN = 10,
  totalMatches,
}: HypothesisTeamConcentrationProps) {
  if (items.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle="Aucune ventilation par équipe n’est disponible pour cette hypothèse."
        title={title}
      />
    );
  }

  const orderedItems = [...items].sort(
    (left, right) =>
      right.matches - left.matches || left.team.localeCompare(right.team, "fr"),
  );
  const computedShares = computeConcentrationShares(
    orderedItems.map((item) => item.matches),
    totalMatches,
  );
  const enrichedItems = orderedItems.map((item, index) => ({
    ...item,
    resolvedShare:
      item.share != null && Number.isFinite(item.share)
        ? Math.min(1, Math.max(0, item.share))
        : (computedShares[index] ?? 0),
  }));
  const visibleCount = Math.max(1, Math.floor(topN));
  const visibleItems = enrichedItems.slice(0, visibleCount);
  const maximumShare = Math.max(
    1e-9,
    ...visibleItems.map((item) => item.resolvedShare),
  );
  const topThreeShare = enrichedItems
    .slice(0, 3)
    .reduce((sum, item) => sum + item.resolvedShare, 0);
  const denominator =
    totalMatches != null && totalMatches > 0
      ? totalMatches
      : orderedItems.reduce((sum, item) => sum + Math.max(0, item.matches), 0);
  const rowGap = 36;
  const width = 760;
  const height = 34 + visibleItems.length * rowGap + 36;
  const labelRight = 214;
  const plotRight = width - 76;
  const plotWidth = plotRight - labelRight;
  const first = enrichedItems[0];
  const summary = first
    ? `${first.team} est l’équipe la plus représentée avec ${formatChartInteger(first.matches)} observation${first.matches > 1 ? "s" : ""} (${formatChartPercent(first.resolvedShare)}). Les trois premières équipes concentrent ${formatChartPercent(topThreeShare)} des ${formatChartInteger(denominator)} observations de référence.`
    : "Aucune concentration calculable.";

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption="Volumes et parts exactes par équipe."
          columns={[
            "Rang",
            "Équipe",
            "Match de référence",
            "Observations",
            "Part",
            "Bilan G / P / A",
            "Profit",
          ]}
          rows={enrichedItems.map((item, index) => ({
            cells: [
              formatChartInteger(index + 1),
              item.team,
              <HistoricalMatchLink
                key={item.matchHref ?? `match-${index}`}
                reference={item}
              >
                {historicalMatchPublicLabel(item)}
              </HistoricalMatchLink>,
              formatChartInteger(item.matches),
              formatChartPercent(item.resolvedShare),
              `${formatChartInteger(item.wins)} / ${formatChartInteger(item.losses)} / ${formatChartInteger(item.voids)}`,
              formatSignedUnits(item.profitUnits),
            ],
            key: `${item.team}-${index}`,
          }))}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: "Part des observations",
        },
        {
          color: evidenceChartPalette.zero,
          label: "Échelle de 0 à la part maximale affichée",
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
        <line
          stroke={evidenceChartPalette.zero}
          strokeWidth={1.5}
          x1={labelRight}
          x2={labelRight}
          y1={18}
          y2={height - 30}
        />
        {visibleItems.map((item, index) => {
          const y = 24 + index * rowGap;
          const barWidth =
            (item.resolvedShare / maximumShare) * Math.max(1, plotWidth);
          const href = historicalMatchHref(item);
          const mark = (
            <rect
              fill={evidenceChartPalette.blue}
              height={18}
              stroke={evidenceChartPalette.blue}
              strokeWidth={1}
              width={Math.max(1, barWidth)}
              x={labelRight}
              y={y}
            >
              <title>
                {`${item.team} : ${formatChartInteger(item.matches)} observations, ${formatChartPercent(item.resolvedShare)} du total, bilan ${formatChartInteger(item.wins)} gagnée${item.wins > 1 ? "s" : ""}, ${formatChartInteger(item.losses)} perdue${item.losses > 1 ? "s" : ""}, ${formatChartInteger(item.voids)} annulée${item.voids > 1 ? "s" : ""}, profit ${formatSignedUnits(item.profitUnits)}, référence ${historicalMatchAccessibleLabel(item)}`}
              </title>
            </rect>
          );

          return (
            <g key={`${item.team}-${index}`}>
              <text
                fill={evidenceChartPalette.ink}
                fontSize={12}
                textAnchor="end"
                x={labelRight - 10}
                y={y + 13}
              >
                {shortTeamName(item.team)}
                <title>{item.team}</title>
              </text>
              {href ? (
                <a
                  aria-label={`Ouvrir le match de référence ${historicalMatchAccessibleLabel(
                    item,
                    `pour ${item.team}`,
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
                x={width - 10}
                y={y + 13}
              >
                {formatChartPercent(item.resolvedShare)}
              </text>
            </g>
          );
        })}
        <text
          fill={evidenceChartPalette.muted}
          fontSize={10}
          textAnchor="start"
          x={labelRight}
          y={height - 10}
        >
          0 %
        </text>
        <text
          fill={evidenceChartPalette.muted}
          fontSize={10}
          textAnchor="end"
          x={plotRight}
          y={height - 10}
        >
          {formatChartPercent(maximumShare)}
        </text>
      </svg>
    </EvidenceChartFrame>
  );
}
