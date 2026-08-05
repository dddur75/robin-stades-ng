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
  displayValue: string;
  status: CoverageRateStatus;
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
  rawSources: unknown,
  canonicalCalendarPropertyIds: readonly string[],
): CoverageDeskModel {
  const sources = asRecord(rawSources, "P0_COVERAGE_SOURCES_INVALID");
  const contract = asRecord(sources.contract, "P0_COVERAGE_CONTRACT_INVALID");
  const catalog = asRecord(sources.grainCatalog, "P0_COVERAGE_CATALOG_INVALID");
  const summary = asRecord(sources.summary, "P0_COVERAGE_SUMMARY_INVALID");
  const propertyReadiness = asRecord(
    sources.propertyReadiness,
    "P0_COVERAGE_PROPERTIES_INVALID",
  );
  const readinessGates = asRecord(
    sources.readinessGates,
    "P0_COVERAGE_GATES_INVALID",
  );

  for (const artifact of [summary, propertyReadiness, readinessGates]) {
    if (
      artifact.provider_calls !== 0 ||
      artifact.r2_writes !== 0 ||
      artifact.purchases !== 0 ||
      artifact.odds_credits !== 0
    ) {
      throw new Error("P0_COVERAGE_EXTERNAL_EFFECT_INVALID");
    }
  }
  const safety = asRecord(contract.safety, "P0_COVERAGE_SAFETY_INVALID");
  if (
    safety.provider_calls !== 0 ||
    safety.r2_writes !== 0 ||
    safety.purchases !== 0 ||
    safety.odds_credits !== 0 ||
    safety.production_locked !== true ||
    safety.promotion !== false ||
    safety.scale_authorized !== false
  ) {
    throw new Error("P0_COVERAGE_SAFETY_INVALID");
  }
  if (
    summary.scale_authorized !== false ||
    summary.promotion !== false ||
    summary.hypergraph_verdict !== "NOT_OPENED_DATA_GATES_INSUFFICIENT" ||
    asArray(summary.properties_unlocked, "P0_COVERAGE_LOCKS_INVALID").length !== 0 ||
    asArray(summary.families_exploitable, "P0_COVERAGE_LOCKS_INVALID").length !== 0 ||
    readinessGates.scale_authorized !== false ||
    readinessGates.promotion !== false ||
    asArray(
      readinessGates.properties_unlocked,
      "P0_COVERAGE_LOCKS_INVALID",
    ).length !== 0 ||
    propertyReadiness.opens_hypergraph !== false ||
    propertyReadiness.hypergraph_verdict !==
      "NOT_OPENED_DATA_GATES_INSUFFICIENT" ||
    asArray(
      propertyReadiness.properties_unlocked,
      "P0_COVERAGE_LOCKS_INVALID",
    ).length !== 0 ||
    asArray(
      propertyReadiness.families_exploitable,
      "P0_COVERAGE_LOCKS_INVALID",
    ).length !== 0
  ) {
    throw new Error("P0_COVERAGE_LOCKS_INVALID");
  }
  if (summary.verdict !== "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL") {
    throw new Error("P0_COVERAGE_VERDICT_INVALID");
  }

  const totalCells = asInteger(summary.total_cells, "P0_COVERAGE_TOTAL_INVALID");
  const closedCells = asInteger(summary.closed_cells, "P0_COVERAGE_CLOSED_INVALID");
  const openCells = asInteger(summary.open_cells, "P0_COVERAGE_OPEN_INVALID");
  const scopes = asRecord(summary.scopes, "P0_COVERAGE_SCOPES_INVALID");
  if (
    totalCells !== 480 ||
    closedCells + openCells !== totalCells ||
    summary.definition_state !== "DEFINITION_CLOSED" ||
    summary.empirical_state !== "OPEN" ||
    scopes.gating !== "P0_2020_2025" ||
    scopes.non_gating !== "EXTENDED_ALL_AVAILABLE" ||
    readinessGates.scope !== "P0_2020_2025" ||
    propertyReadiness.scope !== "P0_2020_2025"
  ) {
    throw new Error("P0_COVERAGE_SUMMARY_INVALID");
  }
  if (closedCells !== 0) {
    throw new Error("P0_COVERAGE_FAMILY_BREAKDOWN_REQUIRED");
  }

  const grid = asRecord(contract.grid, "P0_COVERAGE_GRID_CONTRACT_INVALID");
  const competitions = asArray(
    grid.competitions,
    "P0_COVERAGE_COMPETITIONS_INVALID",
  ).map((item) => asString(item, "P0_COVERAGE_COMPETITION_INVALID"));
  const seasons = asArray(grid.seasons, "P0_COVERAGE_SEASONS_INVALID").map(
    (item) => asInteger(item, "P0_COVERAGE_SEASON_INVALID"),
  );
  const familyIds = asArray(grid.families, "P0_COVERAGE_FAMILIES_INVALID").map(
    (item) => asString(item, "P0_COVERAGE_FAMILY_INVALID"),
  );
  const expectedPerFamily = asInteger(
    grid.expected_per_family,
    "P0_COVERAGE_FAMILY_COUNTS_INVALID",
  );
  if (
    competitions.length !== 5 ||
    seasons.length !== 6 ||
    familyIds.length !== 16 ||
    new Set(competitions).size !== competitions.length ||
    new Set(seasons).size !== seasons.length ||
    new Set(familyIds).size !== familyIds.length ||
    grid.expected_cells !== totalCells ||
    competitions.length * seasons.length * familyIds.length !== totalCells ||
    expectedPerFamily !== competitions.length * seasons.length
  ) {
    throw new Error("P0_COVERAGE_DIMENSIONS_INVALID");
  }

  const catalogScopes = asRecord(catalog.scopes, "P0_COVERAGE_CATALOG_INVALID");
  const catalogP0 = asRecord(
    catalogScopes.P0_2020_2025,
    "P0_COVERAGE_CATALOG_SCOPE_INVALID",
  );
  const catalogCompetitions = asArray(
    catalogP0.competitions,
    "P0_COVERAGE_CATALOG_SCOPE_INVALID",
  );
  const catalogSeasons = asArray(
    catalogP0.seasons,
    "P0_COVERAGE_CATALOG_SCOPE_INVALID",
  );
  if (
    catalogCompetitions.join("|") !== competitions.join("|") ||
    catalogSeasons.join("|") !== seasons.join("|")
  ) {
    throw new Error("P0_COVERAGE_CATALOG_SCOPE_INVALID");
  }

  const familyBindings = asRecord(
    catalog.family_bindings,
    "P0_COVERAGE_FAMILY_BINDINGS_INVALID",
  );
  const grains = asRecord(catalog.grains, "P0_COVERAGE_GRAINS_INVALID");
  const readinessRows = asArray(
    propertyReadiness.family_readiness,
    "P0_COVERAGE_FAMILY_READINESS_INVALID",
  );
  const readinessByFamily = new Map<string, string>();
  for (const rawRow of readinessRows) {
    const row = asRecord(rawRow, "P0_COVERAGE_FAMILY_READINESS_INVALID");
    const family = asString(row.family, "P0_COVERAGE_FAMILY_READINESS_INVALID");
    const unlocked = asArray(
      row.properties_unlocked,
      "P0_COVERAGE_FAMILY_READINESS_INVALID",
    );
    if (
      readinessByFamily.has(family) ||
      row.status !== "BLOCKED_BY_P0_DENOMINATORS" ||
      unlocked.length !== 0
    ) {
      throw new Error("P0_COVERAGE_FAMILY_READINESS_INVALID");
    }
    readinessByFamily.set(family, row.status);
  }
  if (
    readinessByFamily.size !== familyIds.length ||
    familyIds.some((family) => !readinessByFamily.has(family)) ||
    Object.keys(familyBindings).some((family) => !familyIds.includes(family)) ||
    Object.keys(familyBindings).length !== familyIds.length
  ) {
    throw new Error("P0_COVERAGE_FAMILY_BINDINGS_INVALID");
  }

  const families = familyIds
    .map((family) => {
      const binding = asRecord(
        familyBindings[family],
        "P0_COVERAGE_FAMILY_BINDING_INVALID",
      );
      const grain = asRecord(
        grains[asString(binding.grain_id, "P0_COVERAGE_GRAIN_ID_INVALID")],
        "P0_COVERAGE_GRAIN_INVALID",
      );
      return {
        family,
        expectedCells: expectedPerFamily,
        closedCells: 0,
        openCells: expectedPerFamily,
        gate: "BLOCKED_BY_COVERAGE",
        temporalClasses: [
          asString(grain.temporal_class, "P0_COVERAGE_TEMPORAL_CLASS_INVALID"),
        ],
      };
    })
    .sort((left, right) => left.family.localeCompare(right.family, "fr"));

  const aggregateRates = asRecord(
    summary.weighted_aggregates,
    "P0_COVERAGE_AGGREGATES_INVALID",
  );
  if (
    Object.hasOwn(aggregateRates, "coverage_rate") ||
    Object.hasOwn(aggregateRates, "overall_rate") ||
    Object.keys(aggregateRates).sort().join("|") !==
      [...RATE_IDS].sort().join("|")
  ) {
    throw new Error("P0_COVERAGE_RATE_SET_INVALID");
  }
  const rates = RATE_IDS.map((id) => {
    const rate = parseRate(aggregateRates[id], "P0_COVERAGE_AGGREGATE_INVALID");
    return {
      id,
      displayValue: displayRate(rate),
      status: rate.status,
    };
  });

  const calendar = asRecord(
    propertyReadiness.calendar_fatigue,
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
  const summaryCalendar = asRecord(
    summary.calendar_fatigue,
    "P0_COVERAGE_CALENDAR_INVALID",
  );
  if (
    calendarReady !== 0 ||
    calendarTotal !== 17 ||
    calendar.status !== "CLOSED" ||
    summaryCalendar.ready_properties !== calendarReady ||
    summaryCalendar.total_properties !== calendarTotal ||
    summaryCalendar.status !== calendar.status ||
    summaryCalendar.opens_hypergraph !== false
  ) {
    throw new Error("P0_COVERAGE_CALENDAR_STATE_INVALID");
  }

  const gateCounts = asRecord(
    readinessGates.counts,
    "P0_COVERAGE_GATE_COUNTS_INVALID",
  );
  const summaryGateCounts = asRecord(
    summary.gate_counts,
    "P0_COVERAGE_GATE_COUNTS_INVALID",
  );
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
    gateCounts.blocked_by_source !== 2 ||
    summaryGateCounts.functional_total !== gateCounts.functional_total ||
    summaryGateCounts.functional_ready !== gateCounts.functional_ready ||
    summaryGateCounts.blocked_by_coverage !== gateCounts.blocked_by_coverage ||
    summaryGateCounts.blocked_by_source !== gateCounts.blocked_by_source
  ) {
    throw new Error("P0_COVERAGE_GATE_COUNTS_INVALID");
  }

  const coverageGate = asRecord(
    readinessGates.coverage_gate,
    "P0_COVERAGE_COVERAGE_GATE_INVALID",
  );
  if (
    coverageGate.id !== "P0_API_FOOTBALL_COVERAGE" ||
    coverageGate.required_closed_cells !== totalCells ||
    coverageGate.current_closed_cells !== closedCells ||
    coverageGate.status !== "PARTIAL"
  ) {
    throw new Error("P0_COVERAGE_COVERAGE_GATE_INVALID");
  }

  const gateIds = new Set<string>();
  let blockedByCoverage = 0;
  let blockedBySource = 0;
  const gates = asArray(readinessGates.gates, "P0_COVERAGE_GATES_INVALID").map((item) => {
    const gate = asRecord(item, "P0_COVERAGE_GATE_INVALID");
    const id = asString(gate.id, "P0_COVERAGE_GATE_ID_INVALID");
    const status = asString(gate.status, "P0_COVERAGE_GATE_STATUS_INVALID");
    const gateFamilies = asArray(
      gate.families,
      "P0_COVERAGE_GATE_FAMILIES_INVALID",
    ).map((family) =>
      asString(family, "P0_COVERAGE_GATE_FAMILY_INVALID"),
    );
    if (
      gateIds.has(id) ||
      new Set(gateFamilies).size !== gateFamilies.length ||
      gateFamilies.some((family) => !familyIds.includes(family))
    ) {
      throw new Error("P0_COVERAGE_GATE_FAMILIES_INVALID");
    }
    gateIds.add(id);
    if (gateFamilies.length > 0) {
      if (status !== "BLOCKED_BY_COVERAGE") {
        throw new Error("P0_COVERAGE_GATE_STATUS_INVALID");
      }
      blockedByCoverage += 1;
    } else {
      if (
        status !== "BLOCKED_BY_SOURCE" ||
        gate.blocks_p0_api_football_coverage !== false
      ) {
        throw new Error("P0_COVERAGE_GATE_STATUS_INVALID");
      }
      blockedBySource += 1;
    }
    return {
      id,
      status,
      reason: asString(gate.reason, "P0_COVERAGE_GATE_REASON_INVALID"),
    };
  });
  if (
    gates.length !== 10 ||
    blockedByCoverage !== gateCounts.blocked_by_coverage ||
    blockedBySource !== gateCounts.blocked_by_source
  ) {
    throw new Error("P0_COVERAGE_GATE_COUNT_INVALID");
  }

  const levelStates = asRecord(summary.level_states, "P0_COVERAGE_LEVELS_INVALID");
  const levelControls = asRecord(
    summary.level_controls,
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

  return deepFreeze({
    verdict: "COVERAGE_DENOMINATOR_CLOSURE_PARTIAL",
    statusCode: "BLOCKED_BY_COVERAGE",
    definitionState: "DEFINITION_CLOSED",
    empiricalState: "OPEN",
    totalCells,
    closedCells,
    openCells,
    competitionCount: competitions.length,
    seasonCount: seasons.length,
    familyCount: families.length,
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
      providerCalls: summary.provider_calls as number,
      r2Writes: summary.r2_writes as number,
      purchases: summary.purchases as number,
      oddsCredits: summary.odds_credits as number,
    },
  });
}
