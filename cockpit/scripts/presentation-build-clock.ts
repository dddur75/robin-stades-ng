const ISO_INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/u;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

export function requiredIsoInstant(
  value: unknown,
  errorCode: string,
): Date {
  if (typeof value !== "string") {
    throw new Error(errorCode);
  }
  const match = ISO_INSTANT.exec(value);
  if (!match) {
    throw new Error(errorCode);
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[7] === undefined ? 0 : Number(match[7]);
  const offsetMinute = match[8] === undefined ? 0 : Number(match[8]);
  const monthLengths = [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > monthLengths[month - 1] ||
    hour > 23 ||
    minute > 59 ||
    second > 59 ||
    offsetHour > 14 ||
    (offsetHour === 14 && offsetMinute !== 0) ||
    offsetMinute > 59
  ) {
    throw new Error(errorCode);
  }

  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime())) {
    throw new Error(errorCode);
  }
  return instant;
}
