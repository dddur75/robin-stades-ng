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

export type HypothesisSeasonEvidence = HistoricalMatchReference & {
  losses?: number;
  matches: number;
  profitUnits: number;
  roi: number;
  season: string;
  wins?: number;
};

export type HypothesisSeasonBreakdownProps = {
  seasons: readonly HypothesisSeasonEvidence[];
  sourceNote?: string;
  subtitle?: string;
  title?: string;
};

export function HypothesisSeasonBreakdown({
  seasons,
  sourceNote,
  subtitle = "Profit simulé par saison ; les volumes et le ROI restent disponibles dans le tableau.",
  title = "Résultat historique par saison",
}: HypothesisSeasonBreakdownProps) {
  if (seasons.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle="Aucune ventilation saisonnière n’est disponible pour cette hypothèse."
        title={title}
      />
    );
  }

  const geometry = buildDivergingBars(
    seasons.map((season) => season.profitUnits),
    { left: 178, right: 72, rowGap: 40, top: 24, width: 760 },
  );
  const best = seasons.reduce((current, season) =>
    season.profitUnits > current.profitUnits ? season : current,
  );
  const worst = seasons.reduce((current, season) =>
    season.profitUnits < current.profitUnits ? season : current,
  );
  const totalMatches = seasons.reduce(
    (sum, season) => sum + Math.max(0, season.matches),
    0,
  );
  const summary = `${formatChartInteger(totalMatches)} observations sont réparties sur ${formatChartInteger(seasons.length)} saison${seasons.length > 1 ? "s" : ""}. ${best.season} présente le profit le plus élevé (${formatSignedUnits(best.profitUnits)}) et ${worst.season} le plus faible (${formatSignedUnits(worst.profitUnits)}).`;

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption="Mesures historiques exactes ventilées par saison."
          columns={[
            "Saison",
            "Match de référence",
            "Observations",
            "Victoires",
            "Défaites",
            "Profit",
            "ROI",
          ]}
          rows={seasons.map((season, index) => ({
            cells: [
              season.season,
              <HistoricalMatchLink
                key={season.matchHref ?? `match-${index}`}
                reference={season}
              >
                {historicalMatchPublicLabel(season)}
              </HistoricalMatchLink>,
              formatChartInteger(season.matches),
              season.wins == null
                ? "Non disponible"
                : formatChartInteger(season.wins),
              season.losses == null
                ? "Non disponible"
                : formatChartInteger(season.losses),
              formatSignedUnits(season.profitUnits),
              formatChartPercent(season.roi),
            ],
            key: `${season.season}-${index}`,
          }))}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: "Profit positif",
        },
        {
          color: evidenceChartPalette.orange,
          dashed: true,
          label: "Profit négatif ou nul",
          open: true,
        },
        {
          color: evidenceChartPalette.zero,
          label: "Référence 0 u",
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
        viewBox={`0 0 ${geometry.width} ${geometry.height}`}
      >
        <title>{title}</title>
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
          0 u
        </text>

        {geometry.bars.map((bar) => {
          const season = seasons[bar.index];
          if (!season) return null;
          const positive = season.profitUnits > 0;
          const href = historicalMatchHref(season);
          const barMark = (
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
                {`${season.season} : ${formatSignedUnits(season.profitUnits)}, ROI ${formatChartPercent(season.roi)}, ${formatChartInteger(season.matches)} observations, référence ${historicalMatchAccessibleLabel(season)}`}
              </title>
            </rect>
          );

          return (
            <g key={`${season.season}-${bar.index}`}>
              <text
                fill={evidenceChartPalette.ink}
                fontSize={12}
                textAnchor="end"
                x={168}
                y={bar.y + 14}
              >
                {season.season}
              </text>
              {href ? (
                <a
                  aria-label={`Ouvrir le match de référence ${historicalMatchAccessibleLabel(
                    season,
                    `de la saison ${season.season}`,
                  )}`}
                  href={href}
                >
                  {barMark}
                </a>
              ) : (
                barMark
              )}
              <text
                fill={evidenceChartPalette.ink}
                fontSize={11}
                textAnchor={positive ? "start" : "end"}
                x={bar.endX + (positive ? 7 : -7)}
                y={bar.y + 14}
              >
                {formatSignedUnits(season.profitUnits)}
              </text>
            </g>
          );
        })}
      </svg>
    </EvidenceChartFrame>
  );
}
