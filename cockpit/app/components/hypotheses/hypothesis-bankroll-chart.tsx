import {
  EvidenceChartEmptyState,
  EvidenceChartFrame,
  EvidenceFallbackTable,
  HistoricalMatchLink,
} from "./historical-evidence-chart-shell";
import {
  buildBankrollGeometry,
  evidenceChartPalette,
  formatChartNumber,
  formatSignedUnits,
  historicalMatchAccessibleLabel,
  historicalMatchHref,
  historicalMatchPublicLabel,
  makeEvenTicks,
  scaleLinear,
  type HistoricalMatchReference,
} from "./historical-evidence-chart-utils";

export type HypothesisBankrollPoint = HistoricalMatchReference & {
  cumulativeProfitUnits: number;
  label?: string;
  playedAt?: string;
};

export type HypothesisBankrollChartProps = {
  points: readonly HypothesisBankrollPoint[];
  sourceNote?: string;
  subtitle?: string;
  title?: string;
};

const width = 760;
const height = 300;
const padding = { bottom: 42, left: 62, right: 24, top: 24 } as const;

export function HypothesisBankrollChart({
  points,
  sourceNote,
  subtitle = "Profit cumulé en unités, dans l’ordre chronologique des matchs éligibles.",
  title = "Évolution du profit historique cumulé",
}: HypothesisBankrollChartProps) {
  if (points.length === 0) {
    return (
      <EvidenceChartEmptyState
        subtitle="Aucun match historique éligible n’est disponible pour tracer cette courbe."
        title={title}
      />
    );
  }

  const geometry = buildBankrollGeometry(
    points.map((point) => point.cumulativeProfitUnits),
    width,
    height,
    padding,
  );
  const finalProfit = points.at(-1)?.cumulativeProfitUnits ?? 0;
  const ticks = makeEvenTicks(geometry.yMin, geometry.yMax, 5);
  const startLabel = points[0]?.playedAt ?? points[0]?.label ?? "Premier match";
  const endLabel =
    points.at(-1)?.playedAt ?? points.at(-1)?.label ?? "Dernier match";
  const summary = `La courbe part explicitement de 0 u et termine à ${formatSignedUnits(finalProfit)} après ${formatChartNumber(points.length)} match${points.length > 1 ? "s" : ""}. La baisse maximale depuis un sommet atteint ${formatChartNumber(geometry.maxDrawdown)} u.`;

  return (
    <EvidenceChartFrame
      fallback={
        <EvidenceFallbackTable
          caption="Profit cumulé après chaque match historique éligible."
          columns={["Rang", "Match", "Date ou libellé", "Profit cumulé", "État"]}
          rows={[
            {
              cells: ["0", "Départ", "Avant le premier match", "0 u", "Référence"],
              key: "origin",
            },
            ...points.map((point, index) => {
              const previousPeak = Math.max(
                0,
                ...points
                  .slice(0, index)
                  .map((candidate) => candidate.cumulativeProfitUnits),
              );
              const inDrawdown = point.cumulativeProfitUnits < previousPeak;
              return {
                cells: [
                  formatChartNumber(index + 1),
                  <HistoricalMatchLink
                    key={point.matchHref ?? `match-${index}`}
                    reference={point}
                  >
                    {historicalMatchPublicLabel(point)}
                  </HistoricalMatchLink>,
                  point.playedAt ?? point.label ?? "Non renseigné",
                  formatSignedUnits(point.cumulativeProfitUnits),
                  inDrawdown ? "Sous le dernier sommet" : "Nouveau sommet ou égalité",
                ],
                key: point.matchHref ?? `point-${index}`,
              };
            }),
          ]}
        />
      }
      legend={[
        {
          color: evidenceChartPalette.blue,
          label: "Profit cumulé",
        },
        {
          color: evidenceChartPalette.orange,
          dashed: true,
          label: "Segment et zone de baisse depuis un sommet",
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
            geometry.yMin,
            geometry.yMax,
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
                fontSize={11}
                textAnchor="end"
                x={padding.left - 9}
                y={y + 4}
              >
                {formatChartNumber(tick)} u
              </text>
            </g>
          );
        })}

        {geometry.drawdownZones.map((zone) => {
          const start = geometry.points[zone.startIndex];
          const end = geometry.points[zone.endIndex];
          if (!start || !end) return null;
          return (
            <rect
              fill={evidenceChartPalette.orangeOpen}
              height={height - padding.top - padding.bottom}
              key={`${zone.startIndex}-${zone.endIndex}`}
              opacity={0.72}
              width={Math.max(1, end.x - start.x)}
              x={start.x}
              y={padding.top}
            >
              <title>
                {`Période de baisse : sommet ${formatSignedUnits(zone.peakValue)}, creux ${formatSignedUnits(zone.troughValue)}`}
              </title>
            </rect>
          );
        })}

        <line
          stroke={evidenceChartPalette.zero}
          strokeDasharray="5 4"
          strokeWidth={1.5}
          x1={padding.left}
          x2={width - padding.right}
          y1={geometry.zeroY}
          y2={geometry.zeroY}
        />

        {geometry.segments.map((segment) => (
          <line
            key={`${segment.start.index}-${segment.end.index}`}
            stroke={
              segment.drawdown
                ? evidenceChartPalette.orange
                : evidenceChartPalette.blue
            }
            strokeDasharray={segment.drawdown ? "5 3" : undefined}
            strokeLinecap="round"
            strokeWidth={3}
            x1={segment.start.x}
            x2={segment.end.x}
            y1={segment.start.y}
            y2={segment.end.y}
          >
            <title>
              {segment.drawdown
                ? `Baisse vers ${formatSignedUnits(segment.end.value)}`
                : `Profit cumulé ${formatSignedUnits(segment.end.value)}`}
            </title>
          </line>
        ))}

        {geometry.points.map((point, geometryIndex) => {
          const evidencePoint =
            geometryIndex === 0 ? undefined : points[geometryIndex - 1];
          const href = evidencePoint
            ? historicalMatchHref(evidencePoint)
            : undefined;
          const mark = (
            <circle
              cx={point.x}
              cy={point.y}
              fill={
                geometryIndex === 0
                  ? evidenceChartPalette.paper
                  : evidenceChartPalette.blue
              }
              r={geometryIndex === 0 ? 4.5 : 3.5}
              stroke={
                geometryIndex === 0
                  ? evidenceChartPalette.zero
                  : evidenceChartPalette.paper
              }
              strokeWidth={2}
            >
              <title>
                {geometryIndex === 0
                  ? "Départ : 0 u"
                  : `${historicalMatchAccessibleLabel(
                      evidencePoint ?? {},
                      `Match ${geometryIndex}`,
                    )} : ${formatSignedUnits(point.value)}`}
              </title>
            </circle>
          );
          return href ? (
            <a
              aria-label={`Ouvrir le match ${historicalMatchAccessibleLabel(
                evidencePoint ?? {},
                `historique ${geometryIndex}`,
              )}`}
              href={href}
              key={`${href}-${geometryIndex}`}
            >
              {mark}
            </a>
          ) : (
            <g key={`point-${geometryIndex}`}>{mark}</g>
          );
        })}

        <text
          fill={evidenceChartPalette.muted}
          fontSize={11}
          textAnchor="start"
          x={padding.left}
          y={height - 12}
        >
          {startLabel}
        </text>
        <text
          fill={evidenceChartPalette.muted}
          fontSize={11}
          textAnchor="end"
          x={width - padding.right}
          y={height - 12}
        >
          {endLabel}
        </text>
      </svg>
    </EvidenceChartFrame>
  );
}
