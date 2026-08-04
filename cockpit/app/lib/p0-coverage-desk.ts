export type CoverageRateStatus = "KNOWN" | "UNKNOWN" | "EMPTY_VALID" | "NOT_APPLICABLE";

type RawRate = {
  numerator: number | null;
  denominator: number | null;
  value: number | null;
  status: CoverageRateStatus;
  grain: string;
};

export type CoverageRateView = Readonly<{
  id: "scope_completion" | "normalization_integrity" | "content_presence";
  label: string;
  displayValue: string;
  status: CoverageRateStatus;
  explanation: string;
}>;

export type CoverageFamilyView = Readonly<{
  family: string;
  expectedCells: number;
  closedCells: number;
  openCells: number;
  gate: string;
  temporalClasses: readonly string[];
}>;

export type CoverageDeskModel = Readonly<{
  verdict: "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL";
  statusCode: "BLOCKED_BY_COVERAGE";
  definitionState: "DEFINITION_CLOSED";
  empiricalState: "OPEN";
  totalCells: number;
  closedCells: number;
  openCells: number;
  competitionCount: number;
  seasonCount: number;
  familyCount: number;
  calendarReady: number;
  calendarTotal: number;
  functionalGatesReady: number;
  functionalGatesTotal: number;
  rates: readonly CoverageRateView[];
  levels: readonly Readonly<{
    id: string;
    result: string;
    controlStatus: string;
    scope: string;
    canCloseRealCell: boolean;
  }>[];
  gates: readonly Readonly<{ id: string; status: string; reason: string }>[];
  families: readonly CoverageFamilyView[];
  journey: readonly Readonly<{
    id: "data" | "hypothesis" | "strategy" | "matches";
    label: string;
    state: "AVAILABLE" | "CONDITIONS_ONLY" | "BLOCKED";
    detail: string;
    href?: string;
  }>[];
  trust: readonly Readonly<{
    id: "why" | "source" | "invalidate" | "temporality" | "correction";
    question: string;
    answer: string;
  }>[];
  evidence: Readonly<{
    source: string;
    temporalClass: string;
    statisticalCorrection: string;
    providerCalls: number;
    r2Writes: number;
    purchases: number;
    oddsCredits: number;
  }>;
}>;

const RATE_IDS = [
  "scope_completion",
  "normalization_integrity",
  "content_presence",
] as const;

const RATE_EXPLANATIONS: Record<(typeof RATE_IDS)[number], string> = {
  scope_completion: "Scopes complets ou vides valides sur les scopes applicables attendus.",
  normalization_integrity: "Entités uniques normalisées sur les entités brutes admissibles.",
  content_presence: "Slots de contenu observés sur les slots attendus.",
};

function asRecord(value: unknown, code: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(code);
  }
  return value as Record<string, unknown>;
}

function asArray(value: unknown, code: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(code);
  }
  return value;
}

function asString(value: unknown, code: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(code);
  }
  return value;
}

function asInteger(value: unknown, code: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(code);
  }
  return value as number;
}

function asBoolean(value: unknown, code: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(code);
  }
  return value;
}

function nullableInteger(value: unknown, code: string): number | null {
  if (value === null) {
    return null;
  }
  return asInteger(value, code);
}

function parseRate(value: unknown, code: string): RawRate {
  const rate = asRecord(value, code);
  const status = asString(rate.status, code);
  if (!["KNOWN", "UNKNOWN", "EMPTY_VALID", "NOT_APPLICABLE"].includes(status)) {
    throw new Error(code);
  }
  const numerator = nullableInteger(rate.numerator, code);
  const denominator = nullableInteger(rate.denominator, code);
  const rateValue = rate.value;
  if (rateValue !== null && (typeof rateValue !== "number" || rateValue < 0 || rateValue > 1)) {
    throw new Error(code);
  }
  if (status === "UNKNOWN" && (numerator !== null || denominator !== null || rateValue !== null)) {
    throw new Error("P0_COVERAGE_UNKNOWN_RATE_MUST_STAY_NULL");
  }
  return {
    numerator,
    denominator,
    value: rateValue as number | null,
    status: status as CoverageRateStatus,
    grain: asString(rate.grain, code),
  };
}

function displayRate(rate: RawRate): string {
  if (rate.status === "UNKNOWN") {
    return "Non mesuré";
  }
  if (rate.status === "NOT_APPLICABLE") {
    return "Non applicable";
  }
  if (rate.status === "EMPTY_VALID") {
    return "Vide valide";
  }
  if (rate.value === null) {
    throw new Error("P0_COVERAGE_KNOWN_RATE_VALUE_MISSING");
  }
  return new Intl.NumberFormat("fr-FR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(rate.value);
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object" && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
  }
  return value;
}

export function buildP0CoverageDeskModel(
  rawProjection: unknown,
  canonicalCalendarPropertyIds: readonly string[],
): CoverageDeskModel {
  const projection = asRecord(rawProjection, "P0_COVERAGE_PROJECTION_INVALID");
  const privacy = asRecord(projection.privacy, "P0_COVERAGE_PRIVACY_INVALID");
  if (
    privacy.classification !== "PRIVATE_SANITIZED_PROJECTION" ||
    privacy.raw_payloads !== false ||
    privacy.provider_endpoints !== false ||
    privacy.r2_keys !== false ||
    privacy.secrets !== false
  ) {
    throw new Error("P0_COVERAGE_PRIVACY_INVALID");
  }
  if (
    projection.provider_calls !== 0 ||
    projection.r2_writes !== 0 ||
    projection.purchases !== 0 ||
    projection.odds_credits !== 0
  ) {
    throw new Error("P0_COVERAGE_EXTERNAL_EFFECT_INVALID");
  }
  if (projection.verdict !== "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL") {
    throw new Error("P0_COVERAGE_VERDICT_INVALID");
  }

  const summary = asRecord(projection.summary, "P0_COVERAGE_SUMMARY_INVALID");
  const totalCells = asInteger(summary.total_cells, "P0_COVERAGE_TOTAL_INVALID");
  const closedCells = asInteger(summary.closed_cells, "P0_COVERAGE_CLOSED_INVALID");
  const openCells = asInteger(summary.open_cells, "P0_COVERAGE_OPEN_INVALID");
  if (
    totalCells !== 480 ||
    closedCells + openCells !== totalCells ||
    summary.definition_state !== "DEFINITION_CLOSED" ||
    summary.empirical_state !== "OPEN" ||
    summary.gating_scope !== "P0_2020_2025"
  ) {
    throw new Error("P0_COVERAGE_SUMMARY_INVALID");
  }

  const cells = asArray(projection.cells, "P0_COVERAGE_CELLS_INVALID");
  if (cells.length !== totalCells) {
    throw new Error("P0_COVERAGE_CELL_COUNT_INVALID");
  }
  const seenIds = new Set<string>();
  const competitions = new Set<string>();
  const seasons = new Set<number>();
  const familyAccumulator = new Map<
    string,
    {
      expectedCells: number;
      closedCells: number;
      openCells: number;
      gate: string;
      temporalClasses: Set<string>;
    }
  >();

  for (const rawCell of cells) {
    const cell = asRecord(rawCell, "P0_COVERAGE_CELL_INVALID");
    const cellId = asString(cell.cell_id, "P0_COVERAGE_CELL_ID_INVALID");
    if (seenIds.has(cellId)) {
      throw new Error("P0_COVERAGE_DUPLICATE_CELL");
    }
    seenIds.add(cellId);
    if (
      cell.scope !== "P0_2020_2025" ||
      cell.source_endpoint !== "SANITIZED_IN_PRIVATE_PROJECTION" ||
      cell.payload_hash !== null ||
      cell.receipt_hash !== null
    ) {
      throw new Error("P0_COVERAGE_CELL_PRIVACY_INVALID");
    }
    if (
      cell.advertised_coverage !== null ||
      cell.expected_count !== null ||
      cell.received_count !== null ||
      cell.empty_valid_count !== null ||
      cell.invalid_count !== null ||
      cell.coverage_percent !== null ||
      cell.null_rate !== null
    ) {
      throw new Error("P0_COVERAGE_UNPROVEN_COUNT_MUST_STAY_NULL");
    }
    const competition = asString(cell.competition, "P0_COVERAGE_COMPETITION_INVALID");
    const season = asInteger(cell.season, "P0_COVERAGE_SEASON_INVALID");
    const family = asString(cell.family, "P0_COVERAGE_FAMILY_INVALID");
    const temporalClass = asString(
      cell.temporal_class,
      "P0_COVERAGE_TEMPORAL_CLASS_INVALID",
    );
    const gate = asString(cell.gate, "P0_COVERAGE_GATE_INVALID");
    const closureState = asString(cell.closure_state, "P0_COVERAGE_CLOSURE_INVALID");
    competitions.add(competition);
    seasons.add(season);

    const rates = asRecord(cell.rates, "P0_COVERAGE_CELL_RATES_INVALID");
    if (
      Object.hasOwn(rates, "coverage_rate") ||
      Object.hasOwn(rates, "overall_rate") ||
      Object.keys(rates).sort().join("|") !== [...RATE_IDS].sort().join("|")
    ) {
      throw new Error("P0_COVERAGE_RATE_SET_INVALID");
    }
    for (const rateId of RATE_IDS) {
      parseRate(rates[rateId], "P0_COVERAGE_CELL_RATE_INVALID");
    }

    const accumulator = familyAccumulator.get(family) ?? {
      expectedCells: 0,
      closedCells: 0,
      openCells: 0,
      gate,
      temporalClasses: new Set<string>(),
    };
    if (accumulator.gate !== gate) {
      throw new Error("P0_COVERAGE_FAMILY_GATE_INCONSISTENT");
    }
    accumulator.expectedCells += 1;
    if (closureState === "DENOMINATOR_CLOSED_FULL_SCOPE") {
      accumulator.closedCells += 1;
    } else {
      accumulator.openCells += 1;
    }
    accumulator.temporalClasses.add(temporalClass);
    familyAccumulator.set(family, accumulator);
  }

  if (competitions.size !== 5 || seasons.size !== 6 || familyAccumulator.size !== 16) {
    throw new Error("P0_COVERAGE_DIMENSIONS_INVALID");
  }
  if (
    [...familyAccumulator.values()].some(
      (item) => item.expectedCells !== 30 || item.closedCells + item.openCells !== 30,
    )
  ) {
    throw new Error("P0_COVERAGE_FAMILY_COUNTS_INVALID");
  }

  const aggregateRates = asRecord(
    projection.weighted_aggregates,
    "P0_COVERAGE_AGGREGATES_INVALID",
  );
  const rateLabels = asRecord(projection.rate_labels, "P0_COVERAGE_RATE_LABELS_INVALID");
  const rates = RATE_IDS.map((id) => {
    const rate = parseRate(aggregateRates[id], "P0_COVERAGE_AGGREGATE_INVALID");
    return {
      id,
      label: asString(rateLabels[id], "P0_COVERAGE_RATE_LABEL_INVALID"),
      displayValue: displayRate(rate),
      status: rate.status,
      explanation: RATE_EXPLANATIONS[id],
    };
  });

  const calendar = asRecord(
    projection.calendar_fatigue,
    "P0_COVERAGE_CALENDAR_INVALID",
  );
  const calendarProperties = asArray(
    calendar.properties,
    "P0_COVERAGE_CALENDAR_PROPERTIES_INVALID",
  );
  const configuredCalendarIds = calendarProperties
    .map((item) => asString(asRecord(item, "P0_COVERAGE_CALENDAR_PROPERTY_INVALID").id, "P0_COVERAGE_CALENDAR_PROPERTY_INVALID"))
    .sort();
  const canonicalIds = [...canonicalCalendarPropertyIds].sort();
  if (
    configuredCalendarIds.length !== 17 ||
    configuredCalendarIds.join("|") !== canonicalIds.join("|")
  ) {
    throw new Error("P0_COVERAGE_CALENDAR_CATALOG_MISMATCH");
  }
  const calendarReady = asInteger(
    calendar.ready_properties,
    "P0_COVERAGE_CALENDAR_READY_INVALID",
  );
  const calendarTotal = asInteger(
    calendar.total_properties,
    "P0_COVERAGE_CALENDAR_TOTAL_INVALID",
  );
  if (calendarReady !== 0 || calendarTotal !== 17 || calendar.status !== "CLOSED") {
    throw new Error("P0_COVERAGE_CALENDAR_STATE_INVALID");
  }

  const gateCounts = asRecord(projection.gate_counts, "P0_COVERAGE_GATE_COUNTS_INVALID");
  const functionalGatesReady = asInteger(
    gateCounts.functional_ready,
    "P0_COVERAGE_GATE_READY_INVALID",
  );
  const functionalGatesTotal = asInteger(
    gateCounts.functional_total,
    "P0_COVERAGE_GATE_TOTAL_INVALID",
  );
  if (
    functionalGatesReady !== 0 ||
    functionalGatesTotal !== 8 ||
    gateCounts.blocked_by_coverage !== 8 ||
    gateCounts.blocked_by_source !== 2
  ) {
    throw new Error("P0_COVERAGE_GATE_COUNTS_INVALID");
  }

  const gates = asArray(projection.gates, "P0_COVERAGE_GATES_INVALID").map((item) => {
    const gate = asRecord(item, "P0_COVERAGE_GATE_INVALID");
    return {
      id: asString(gate.id, "P0_COVERAGE_GATE_ID_INVALID"),
      status: asString(gate.status, "P0_COVERAGE_GATE_STATUS_INVALID"),
      reason: asString(gate.reason, "P0_COVERAGE_GATE_REASON_INVALID"),
    };
  });
  if (gates.length !== 10) {
    throw new Error("P0_COVERAGE_GATE_COUNT_INVALID");
  }

  const levelStates = asRecord(projection.level_states, "P0_COVERAGE_LEVELS_INVALID");
  const levelControls = asRecord(
    projection.level_controls,
    "P0_COVERAGE_LEVEL_CONTROLS_INVALID",
  );
  const levels = ["E0", "E1", "E2", "E3", "E4"].map((id) => {
    const control = asRecord(levelControls[id], "P0_COVERAGE_LEVEL_CONTROL_INVALID");
    return {
      id,
      result: asString(levelStates[id], "P0_COVERAGE_LEVEL_RESULT_INVALID"),
      controlStatus: asString(control.status, "P0_COVERAGE_LEVEL_STATUS_INVALID"),
      scope: asString(control.scope, "P0_COVERAGE_LEVEL_SCOPE_INVALID"),
      canCloseRealCell: asBoolean(
        control.can_close_real_cell,
        "P0_COVERAGE_LEVEL_AUTHORITY_INVALID",
      ),
    };
  });
  if (
    levels[0]?.result !== "PASS_DEFINITION_ONLY" ||
    levels.slice(1).some((level) => level.result !== "NOT_RUN")
  ) {
    throw new Error("P0_COVERAGE_LEVEL_STATE_INVALID");
  }

  const navigation = asRecord(
    projection.navigation_gates,
    "P0_COVERAGE_NAVIGATION_INVALID",
  );
  if (
    navigation.data !== "AVAILABLE" ||
    navigation.hypothesis !== "BLOCKED_BY_DATA" ||
    navigation.strategy !== "BLOCKED_BY_SCIENCE" ||
    navigation.matches !== "BLOCKED_BY_MEMBERSHIP_SET"
  ) {
    throw new Error("P0_COVERAGE_NAVIGATION_INVALID");
  }

  const families = [...familyAccumulator.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "fr"))
    .map(([family, item]) => ({
      family,
      expectedCells: item.expectedCells,
      closedCells: item.closedCells,
      openCells: item.openCells,
      gate: item.gate,
      temporalClasses: [...item.temporalClasses].sort(),
    }));

  return deepFreeze({
    verdict: "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL",
    statusCode: "BLOCKED_BY_COVERAGE",
    definitionState: "DEFINITION_CLOSED",
    empiricalState: "OPEN",
    totalCells,
    closedCells,
    openCells,
    competitionCount: competitions.size,
    seasonCount: seasons.size,
    familyCount: familyAccumulator.size,
    calendarReady,
    calendarTotal,
    functionalGatesReady,
    functionalGatesTotal,
    rates,
    levels,
    gates,
    families,
    journey: [
      {
        id: "data",
        label: "Données",
        state: "AVAILABLE",
        detail: "Grille P0 consultable",
        href: "#coverage-p0-table",
      },
      {
        id: "hypothesis",
        label: "Hypothèse",
        state: "CONDITIONS_ONLY",
        detail: "Conditions visibles, calcul fermé",
        href: "#gates-calendar-fatigue",
      },
      {
        id: "strategy",
        label: "Stratégie",
        state: "BLOCKED",
        detail: "Attend les contrôles scientifiques",
      },
      {
        id: "matches",
        label: "Matchs",
        state: "BLOCKED",
        detail: "Attend un ensemble d’appartenance gelé",
      },
    ],
    trust: [
      {
        id: "why",
        question: "Pourquoi est-il affiché ?",
        answer: "Pour expliquer pourquoi la recherche d’hypothèses reste fermée.",
      },
      {
        id: "source",
        question: "Sur quelles données repose-t-il ?",
        answer: "Sur la grille P0 définie à E0 et la preuve PR26 réutilisée sans census par cellule.",
      },
      {
        id: "invalidate",
        question: "Qu’est-ce qui pourrait l’invalider ?",
        answer: "Un changement du contrat amont, du catalogue de grains ou des hashes de preuve.",
      },
      {
        id: "temporality",
        question: "Est-il historique, reconstruit ou prospectif ?",
        answer: "E0 est une preuve synthétique de définition : ni résultat historique, ni reconstruit, ni prospectif.",
      },
      {
        id: "correction",
        question: "A-t-il survécu aux corrections statistiques ?",
        answer: "Sans objet : aucune hypothèse ni performance n’est calculée à ce niveau.",
      },
    ],
    evidence: {
      source: "Preuve PR26 réutilisée · census P0 par cellule non matérialisé",
      temporalClass: "E0 synthétique de définition",
      statisticalCorrection: "Sans objet",
      providerCalls: projection.provider_calls as number,
      r2Writes: projection.r2_writes as number,
      purchases: projection.purchases as number,
      oddsCredits: projection.odds_credits as number,
    },
  });
}
