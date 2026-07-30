import type { HypothesisTreeNode } from "./hypothesis-universe";

export type FilterOperator = "ET" | "OU" | "SAUF";

export type UnderstoodFilter = {
  field:
    | "competition"
    | "family"
    | "status"
    | "support"
    | "text";
  id: string;
  label: string;
  operator: FilterOperator;
  segment: number;
  value: number | string;
};

type QuerySegment = {
  index: number;
  operator: FilterOperator;
  start: number;
  text: string;
};

const familyTerms: Array<[RegExp, string, string]> = [
  [/\bm[ée]t[ée]o\b/i, "WEATHER", "Météo"],
  [/\bvent\b|\brafale/i, "WEATHER", "Vent ou rafales"],
  [/\bgardien\b/i, "GOALKEEPER", "Gardien"],
  [
    /\bformation\b|\b4[- ]?3[- ]?3\b|\b4[- ]?4[- ]?2\b/i,
    "FORMATION_STRUCTURE",
    "Formations",
  ],
  [/\babsence\b|\babsent/i, "ABSENCE_RETURN", "Absences"],
  [/\bd[ée]placement/i, "TRAVEL_LOGISTICS", "Déplacements"],
  [/\brepos\b|\bfatigue\b/i, "CALENDAR_FATIGUE", "Fatigue et repos"],
  [/\bcentre(s)?\b|\battaque\b/i, "ATTACK", "Attaque et centres"],
  [/\bmarch[ée]\b|\bcote\b|\bmarge\b/i, "MARKET", "Marché"],
];

const competitionTerms: Array<[RegExp, string]> = [
  [/\bligue ?1\b/i, "Ligue 1"],
  [/\bpremier league\b/i, "Premier League"],
  [/\bliga\b|\bla liga\b/i, "La Liga"],
  [/\bbundesliga\b/i, "Bundesliga"],
  [/\bserie ?a\b/i, "Serie A"],
];

function tokenizeQuery(source: string): QuerySegment[] {
  const operatorPattern = /\b(ET|OU|SAUF)\b/giu;
  const segments: QuerySegment[] = [];
  let currentOperator: FilterOperator = "ET";
  let segmentStart = 0;
  let index = 0;

  for (const match of source.matchAll(operatorPattern)) {
    const operatorStart = match.index;
    const text = source.slice(segmentStart, operatorStart);
    if (text.trim()) {
      segments.push({
        index,
        operator: currentOperator,
        start: segmentStart,
        text,
      });
      index += 1;
    }
    currentOperator = match[1].toLocaleUpperCase("fr-FR") as FilterOperator;
    segmentStart = operatorStart + match[0].length;
  }

  const text = source.slice(segmentStart);
  if (text.trim()) {
    segments.push({
      index,
      operator: currentOperator,
      start: segmentStart,
      text,
    });
  }
  return segments;
}

export function parseFrenchHypothesisQuery(query: string): UnderstoodFilter[] {
  const normalized = query.trim();
  if (!normalized) return [];

  const clauses: Array<UnderstoodFilter & { position: number }> = [];
  const seen = new Set<string>();
  const segments = tokenizeQuery(normalized);

  const add = (
    segment: QuerySegment,
    relativePosition: number,
    filter: Omit<UnderstoodFilter, "operator" | "segment">,
  ) => {
    if (seen.has(filter.id)) return;
    seen.add(filter.id);
    clauses.push({
      ...filter,
      operator: segment.operator,
      position: segment.start + relativePosition,
      segment: segment.index,
    });
  };

  for (const segment of segments) {
    for (const [pattern, family, label] of familyTerms) {
      const match = pattern.exec(segment.text);
      if (!match) continue;
      add(segment, match.index, {
        field: "family",
        id: `family:${family}`,
        label,
        value: family,
      });
    }

    for (const [pattern, competition] of competitionTerms) {
      const match = pattern.exec(segment.text);
      if (!match) continue;
      add(segment, match.index, {
        field: "competition",
        id: `competition:${competition}`,
        label: competition,
        value: competition,
      });
    }

    const blocked = /\bbloqu[ée]e?s?\b/i.exec(segment.text);
    if (blocked) {
      add(segment, blocked.index, {
        field: "status",
        id: "status:blocked",
        label: "Branches bloquées",
        value: "DATA_GATE_BLOCKED",
      });
    }

    const longTail = /\blongue tra[îi]ne\b|\brare(s)?\b/i.exec(segment.text);
    if (longTail) {
      add(segment, longTail.index, {
        field: "status",
        id: "status:long-tail",
        label: "Longue traîne",
        value: "LONG_TAIL_WATCHLIST",
      });
    }

    const support =
      /(?:plus de|support\s*(?:>|sup[ée]rieur [àa]))\s*(\d+)\s*(?:matchs?)?/i.exec(
        segment.text,
      );
    if (support) {
      add(segment, support.index, {
        field: "support",
        id: `support:${support[1]}`,
        label: `Plus de ${support[1]} matchs`,
        value: Number(support[1]),
      });
    }

    const concepts = [
      ["Vent fort", /\bvent(?:\s+fort)?\b|\brafale/i],
      ["Centres", /\bcentre(s)?\b/i],
      ["faux pied", /\bfaux pied\b/i],
      ["duo central", /\bduo central\b|\bcentraux\b/i],
      [
        "troisième déplacement",
        /\btroisi[èe]me d[ée]placement\b|\b3e d[ée]placement\b/i,
      ],
    ] as const;
    for (const [label, pattern] of concepts) {
      const match = pattern.exec(segment.text);
      if (!match) continue;
      add(segment, match.index, {
        field: "text",
        id: `text:${label}`,
        label,
        value: label,
      });
    }
  }

  return clauses
    .sort((left, right) => left.position - right.position)
    .map((filter) => ({
      field: filter.field,
      id: filter.id,
      label: filter.label,
      operator: filter.operator,
      segment: filter.segment,
      value: filter.value,
    }));
}

function normalizeSearchText(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("fr-FR");
}

function nodeMatchesClause(
  node: HypothesisTreeNode,
  clause: UnderstoodFilter,
) {
  switch (clause.field) {
    case "family":
      return (
        node.family === clause.value ||
        normalizeSearchText(JSON.stringify(node.technical_rule)).includes(
          normalizeSearchText(String(clause.value)),
        )
      );
    case "status":
      return (
        node.materialization_disposition === clause.value ||
        node.status === clause.value ||
        node.data_gates.includes(String(clause.value))
      );
    case "support":
      return node.support != null && node.support > Number(clause.value);
    case "competition":
      return node.tags.some(
        (tag) =>
          normalizeSearchText(tag) ===
          normalizeSearchText(String(clause.value)),
      );
    case "text": {
      const haystack = normalizeSearchText(
        `${node.display_rule_fr} ${node.subfamily} ${node.tags.join(" ")} ${JSON.stringify(node.technical_rule)}`,
      );
      const requested = normalizeSearchText(String(clause.value));
      const synonyms: Record<string, string[]> = {
        centres: ["centre", "cross"],
        "vent fort": ["vent", "wind", "gust"],
      };
      return (synonyms[requested] ?? [requested]).some((needle) =>
        haystack.includes(needle),
      );
    }
  }
}

export function nodeMatchesUnderstoodFilters(
  node: HypothesisTreeNode,
  filters: UnderstoodFilter[],
) {
  if (!filters.length) return true;
  const segments = new Map<
    number,
    { filters: UnderstoodFilter[]; operator: FilterOperator }
  >();

  filters.forEach((filter, fallbackIndex) => {
    const segmentIndex = Number.isInteger(filter.segment)
      ? filter.segment
      : fallbackIndex;
    const current = segments.get(segmentIndex);
    if (current) current.filters.push(filter);
    else {
      segments.set(segmentIndex, {
        filters: [filter],
        operator: filter.operator,
      });
    }
  });

  const ordered = [...segments.entries()].sort(
    ([left], [right]) => left - right,
  );
  const disjunctions: boolean[] = [];
  let conjunction = true;

  for (const [, segment] of ordered) {
    const segmentMatches = segment.filters.every((filter) =>
      nodeMatchesClause(node, filter),
    );
    const value =
      segment.operator === "SAUF" ? !segmentMatches : segmentMatches;
    if (segment.operator === "OU") {
      disjunctions.push(conjunction);
      conjunction = value;
    } else {
      conjunction = conjunction && value;
    }
  }

  disjunctions.push(conjunction);
  return disjunctions.some(Boolean);
}
