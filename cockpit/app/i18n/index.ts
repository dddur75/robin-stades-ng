import { frFR, type TranslationKey } from "./fr-FR";

export const activeLocale = "fr-FR" as const;
export const publicTimeZone = "Europe/Paris" as const;

export function t(
  key: TranslationKey,
  variables: Record<string, string | number> = {},
): string {
  return Object.entries(variables).reduce(
    (value, [name, replacement]) =>
      value.replaceAll(`{${name}}`, String(replacement)),
    frFR[key],
  );
}

export function formatDateTime(value: string | Date, includeYear = false) {
  return new Intl.DateTimeFormat(activeLocale, {
    day: "numeric",
    month: "long",
    ...(includeYear ? { year: "numeric" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
    timeZone: publicTimeZone,
  })
    .format(new Date(value))
    .replace(":", " h ");
}

export function formatDate(value: string | Date) {
  return new Intl.DateTimeFormat(activeLocale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: publicTimeZone,
  }).format(new Date(value));
}

export function formatShortDate(value: string | Date) {
  return new Intl.DateTimeFormat(activeLocale, {
    day: "2-digit",
    month: "short",
    timeZone: publicTimeZone,
  }).format(new Date(value));
}

export function formatNumber(value: number, maximumFractionDigits = 0) {
  return new Intl.NumberFormat(activeLocale, { maximumFractionDigits }).format(
    value,
  );
}

export function formatPercent(value: number | null | undefined) {
  return value == null
    ? t("common.notApplicable")
    : new Intl.NumberFormat(activeLocale, {
        style: "percent",
        maximumFractionDigits: 1,
      }).format(value);
}

export function formatUnits(value: number) {
  return `${formatNumber(value, 1)} ${value > 1 ? "unités" : "unité"}`;
}

export function formatBytes(value: number) {
  const formatter = new Intl.NumberFormat(activeLocale, {
    maximumFractionDigits: 1,
  });
  if (value >= 1_000_000_000) return `${formatter.format(value / 1_000_000_000)} Go`;
  if (value >= 1_000_000) return `${formatter.format(value / 1_000_000)} Mo`;
  if (value >= 1_000) return `${formatter.format(value / 1_000)} ko`;
  return `${formatter.format(value)} octets`;
}
