export type HistoricalMatchReference = {
  matchDate?: string;
  matchHref?: string;
  matchId?: string;
  matchLabel?: string;
};

export type ChartPadding = {
  bottom: number;
  left: number;
  right: number;
  top: number;
};

export type SvgPoint = {
  index: number;
  value: number;
  x: number;
  y: number;
};

export type BankrollSegment = {
  drawdown: boolean;
  end: SvgPoint;
  start: SvgPoint;
};

export type DrawdownZone = {
  endIndex: number;
  peakValue: number;
  startIndex: number;
  troughValue: number;
};

export type BankrollGeometry = {
  drawdownZones: DrawdownZone[];
  height: number;
  maxDrawdown: number;
  points: SvgPoint[];
  segments: BankrollSegment[];
  width: number;
  yMax: number;
  yMin: number;
  zeroY: number;
};

export type DivergingBar = {
  endX: number;
  index: number;
  value: number;
  width: number;
  x: number;
  y: number;
};

export const evidenceChartPalette = {
  blue: "#2f67a5",
  blueOpen: "#e8f0f8",
  gold: "#a96f19",
  goldOpen: "#fbf2df",
  grid: "#d8dee8",
  ink: "#172033",
  muted: "#5d6878",
  orange: "#b8622c",
  orangeOpen: "#fff0e6",
  paper: "#ffffff",
  zero: "#3f4a5a",
} as const;

const frenchNumber = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
});

const frenchInteger = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 0,
});

const frenchPercent = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 1,
  style: "percent",
});

const frenchMatchDate = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
  year: "numeric",
});

export function formatChartNumber(value: number): string {
  return frenchNumber.format(value);
}

export function formatChartInteger(value: number): string {
  return frenchInteger.format(value);
}

export function formatChartPercent(value: number): string {
  return frenchPercent.format(value);
}

export function formatSignedUnits(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatChartNumber(value)} u`;
}

export function historicalMatchHref(
  reference: HistoricalMatchReference,
): string | undefined {
  if (reference.matchHref) return reference.matchHref;
  if (!reference.matchId) return undefined;
  return `/matchs/historique/${encodeURIComponent(reference.matchId)}`;
}

export function historicalMatchPublicLabel(
  reference: HistoricalMatchReference,
  fallback = "Match historique de référence",
): string {
  const label = reference.matchLabel?.trim();
  return label ? label : fallback;
}

export function historicalMatchAccessibleLabel(
  reference: HistoricalMatchReference,
  fallback?: string,
): string {
  const label = historicalMatchPublicLabel(reference, fallback);
  const matchDate = reference.matchDate;
  if (!matchDate || !/^\d{4}-\d{2}-\d{2}$/u.test(matchDate)) return label;
  const timestamp = Date.parse(`${matchDate}T00:00:00Z`);
  return Number.isFinite(timestamp)
    ? `${label}, ${frenchMatchDate.format(new Date(timestamp))}`
    : label;
}

export function scaleLinear(
  value: number,
  domainMin: number,
  domainMax: number,
  rangeMin: number,
  rangeMax: number,
): number {
  if (!Number.isFinite(value)) return rangeMin;
  if (domainMax === domainMin) return (rangeMin + rangeMax) / 2;
  const ratio = (value - domainMin) / (domainMax - domainMin);
  return rangeMin + ratio * (rangeMax - rangeMin);
}

export function chartDomain(
  values: readonly number[],
  includeZero = true,
  paddingRatio = 0.08,
): [number, number] {
  const finiteValues = values.filter(Number.isFinite);
  if (includeZero) finiteValues.push(0);
  if (finiteValues.length === 0) return [-1, 1];

  let minimum = Math.min(...finiteValues);
  let maximum = Math.max(...finiteValues);
  if (minimum === maximum) {
    const fallbackPadding = Math.max(Math.abs(minimum) * 0.1, 1);
    return [minimum - fallbackPadding, maximum + fallbackPadding];
  }

  const padding = (maximum - minimum) * paddingRatio;
  minimum -= padding;
  maximum += padding;
  return [minimum, maximum];
}

export function buildBankrollGeometry(
  cumulativeProfitValues: readonly number[],
  width = 760,
  height = 300,
  padding: ChartPadding = { bottom: 42, left: 62, right: 24, top: 24 },
): BankrollGeometry {
  const values = [
    0,
    ...cumulativeProfitValues.map((value) =>
      Number.isFinite(value) ? value : 0,
    ),
  ];
  const [yMin, yMax] = chartDomain(values, true);
  const plotWidth = Math.max(1, width - padding.left - padding.right);
  const plotHeight = Math.max(1, height - padding.top - padding.bottom);
  const denominator = Math.max(1, values.length - 1);
  const points = values.map((value, index) => ({
    index,
    value,
    x: padding.left + (index / denominator) * plotWidth,
    y: scaleLinear(
      value,
      yMin,
      yMax,
      padding.top + plotHeight,
      padding.top,
    ),
  }));

  let peak = values[0] ?? 0;
  let zoneStart: number | null = null;
  let zonePeak = peak;
  let zoneTrough = peak;
  let maxDrawdown = 0;
  const drawdownFlags = values.map(() => false);
  const drawdownZones: DrawdownZone[] = [];

  for (let index = 1; index < values.length; index += 1) {
    const value = values[index] ?? 0;
    if (value >= peak) {
      if (zoneStart !== null) {
        drawdownZones.push({
          endIndex: index,
          peakValue: zonePeak,
          startIndex: zoneStart,
          troughValue: zoneTrough,
        });
        zoneStart = null;
      }
      peak = value;
      zonePeak = value;
      zoneTrough = value;
      continue;
    }

    drawdownFlags[index] = true;
    if (zoneStart === null) {
      zoneStart = index - 1;
      zonePeak = peak;
      zoneTrough = value;
    } else {
      zoneTrough = Math.min(zoneTrough, value);
    }
    maxDrawdown = Math.max(maxDrawdown, peak - value);
  }

  if (zoneStart !== null) {
    drawdownZones.push({
      endIndex: values.length - 1,
      peakValue: zonePeak,
      startIndex: zoneStart,
      troughValue: zoneTrough,
    });
  }

  const segments = points.slice(1).map((end, offset) => ({
    drawdown: drawdownFlags[offset + 1] ?? false,
    end,
    start: points[offset] as SvgPoint,
  }));

  return {
    drawdownZones,
    height,
    maxDrawdown,
    points,
    segments,
    width,
    yMax,
    yMin,
    zeroY: scaleLinear(
      0,
      yMin,
      yMax,
      padding.top + plotHeight,
      padding.top,
    ),
  };
}

export function buildDivergingBars(
  values: readonly number[],
  options: {
    bottom?: number;
    height?: number;
    left?: number;
    right?: number;
    rowGap?: number;
    top?: number;
    width?: number;
  } = {},
): {
  bars: DivergingBar[];
  height: number;
  maximumAbsoluteValue: number;
  width: number;
  zeroX: number;
} {
  const width = options.width ?? 760;
  const top = options.top ?? 28;
  const bottom = options.bottom ?? 38;
  const left = options.left ?? 190;
  const right = options.right ?? 60;
  const rowGap = options.rowGap ?? 38;
  const minimumHeight = top + bottom + Math.max(1, values.length) * rowGap;
  const height = Math.max(options.height ?? 0, minimumHeight);
  const maximumAbsoluteValue = Math.max(
    1e-9,
    ...values.filter(Number.isFinite).map((value) => Math.abs(value)),
  );
  const zeroX = (left + width - right) / 2;
  const halfPlotWidth = (width - right - left) / 2;

  const bars = values.map((rawValue, index) => {
    const value = Number.isFinite(rawValue) ? rawValue : 0;
    const endX =
      zeroX + (value / maximumAbsoluteValue) * Math.max(1, halfPlotWidth);
    return {
      endX,
      index,
      value,
      width: Math.abs(endX - zeroX),
      x: Math.min(zeroX, endX),
      y: top + index * rowGap + 7,
    };
  });

  return { bars, height, maximumAbsoluteValue, width, zeroX };
}

export function computeConcentrationShares(
  volumes: readonly number[],
  denominator?: number,
): number[] {
  const cleanVolumes = volumes.map((value) =>
    Number.isFinite(value) && value > 0 ? value : 0,
  );
  const total =
    denominator != null && Number.isFinite(denominator) && denominator > 0
      ? denominator
      : cleanVolumes.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return cleanVolumes.map(() => 0);
  return cleanVolumes.map((value) => value / total);
}

export function makeEvenTicks(
  minimum: number,
  maximum: number,
  count = 5,
): number[] {
  const safeCount = Math.max(2, Math.floor(count));
  if (minimum === maximum) return [minimum];
  return Array.from(
    { length: safeCount },
    (_, index) => minimum + (index / (safeCount - 1)) * (maximum - minimum),
  );
}
