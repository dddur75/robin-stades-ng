import { statusCatalogue } from "../i18n/status-translations";

export type CoverageState =
  | "captured"
  | "upcoming"
  | "empty"
  | "blocked"
  | "late"
  | "error";

export type PresentationWindow = {
  id: string;
  fixtureId: string;
  family: string;
  label: string;
  opensAt: string;
  dueAt: string;
  cutoffAt: string;
  kickoffAt: string;
  status: string;
  active: boolean;
  acknowledged: boolean;
  policyVersion: string;
};

export type MatchPresentation = {
  id: string;
  providerId: string;
  internalId: string;
  competition: string;
  home: string;
  away: string;
  homeTeamId: string;
  awayTeamId: string;
  homeIdentityStatus: string;
  awayIdentityStatus: string;
  homeIdentitySource: string | null;
  awayIdentitySource: string | null;
  kickoff: string;
  matchStatus: string;
  dataStatus: string;
  coverage: number;
  nextCapture: string | null;
  nextFamily: string | null;
  nextFamilies: string[];
  observedOdds: boolean;
  hypotheses: number;
  families: Record<string, CoverageState>;
  probabilities: {
    home: number | null;
    draw: number | null;
    away: number | null;
  };
  timeline: PresentationWindow[];
};

export type NextCapturePresentation = {
  id: string;
  dueAt: string;
  opensAt: string;
  cutoffAt: string;
  match: string;
  fixtureCount: number;
  fixtureIds: string[];
  family: string;
  families: string[];
  status: string;
};

export type FreshnessPresentation = {
  status: "FRESHNESS_CURRENT" | "FRESHNESS_UPDATING" | "FRESHNESS_STALE" | "FRESHNESS_INVALID";
  generatedAt: string;
  ageMinutes: number | null;
  reason: string;
  threshold: string;
  lastWorkflowAt: string | null;
};

export type OperationalEvidence = {
  generatedAt: string;
  sourceRun: string;
  sourceRevision: string;
  sourceWorkflow: string;
  status: string;
  origin: string;
  fixtures: number;
  activeWindows: number;
  inactiveLegacyWindows: number;
  dueWindows: number;
  physicalEvidence: number;
  fixtureCaptures: number;
  deepObservations: number;
  emptyResponses: number;
  errors: number;
  delays: number;
  candidates: number;
  decisions: number;
  r2: {
    objects: number;
    bytes: number;
    verified: number;
    lag: number;
    deletions: number;
    replayStatus: string;
  };
  postgresql: {
    migration: string;
    tables: number;
    inserts: number;
    duplicatesAvoided: number;
    lag: number;
    reconstructionStatus: string;
    payloadBodyRows: number;
  };
  ledger: {
    events: number;
    headHash: string;
  };
  providers: {
    apiFootballCalls: number;
    oddsApiCredits: number;
    apiFootballCap: number;
    oddsApiCap: number;
  };
  invariants: Record<string, boolean | string | number>;
  freshness: FreshnessPresentation;
};

export type LeaguePresentation = {
  competition: string;
  captureProfile: string;
  fixtures: number;
  teams: number;
  identitySlotsVerified: number;
  identitySlotsExpected: number;
  activeWindows: number;
  nextCaptures: number;
  captures: number;
  deepObservations: number;
  emptyResponses: number;
  apiFootballCalls: number;
  oddsApiCredits: number;
  gate: string;
  r2: string;
  postgresql: string;
  replay: string;
  coverage: number;
};

export type PresentationModel = {
  dashboard: {
    operationalEvidence: OperationalEvidence;
    bankroll: {
      initialUnits: number | null;
      currentUnits: number | null;
      policySource: string | null;
    };
  };
  matches: MatchPresentation[];
  leagues: LeaguePresentation[];
  nextCaptures: NextCapturePresentation[];
  observatory: {
    gateRows: Array<{
      name: string;
      technicalName: string;
      status: string;
      passed: number;
      total: number;
      reason: string;
    }>;
  };
  hypotheses: Array<{
    id: string;
    title: string;
    mechanism: string;
    requiredData: string[];
    minimumSupport: number;
    observations: number;
    coverage: number;
    status: string;
    frozen: boolean;
  }>;
  results: Record<string, unknown>;
  expert: Record<string, unknown>;
  system: {
    freshness: FreshnessPresentation;
    statusCoverage: {
      total: number;
      translated: number;
      percentage: number;
      unknown: string[];
    };
    encodingCorrections: {
      count: number;
      fields: string[];
      cleanerEnabled: boolean;
    };
    validationErrors: string[];
  };
  oddsSnapshots: Array<{
    id: string;
    fixtureId: string;
    observedAt: string;
    provider: string;
    bookmakers: number;
    quotes: number;
    markets: string[];
    hash: string;
    probabilities: {
      home: number | null;
      draw: number | null;
      away: number | null;
    };
  }>;
};

type UnknownRecord = Record<string, unknown>;

const displayedFamilies = [
  "FIXTURE",
  "TEAM",
  "SQUAD",
  "PLAYER_STATUS",
  "INJURY",
  "LINEUP",
  "FORMATION",
  "ODDS",
] as const;

const gateNames: Record<string, string> = {
  PROSPECTIVE_PLAYER_GATE: "Joueurs",
  PROSPECTIVE_INJURY_GATE: "Blessures",
  PROSPECTIVE_LINEUP_GATE: "Compositions",
  PROSPECTIVE_FORMATION_GATE: "Formations",
  PROSPECTIVE_MARKET_GATE: "Marché",
};

const gateReasons: Record<string, string> = {
  NO_PROSPECTIVE_OBSERVATION: "Aucune observation prospective admissible.",
  LINEUP_GATE_REQUIRED: "La composition doit d’abord être vérifiée.",
  THREE_PRIOR_CAPTURES_REQUIRED: "Trois captures antérieures sont requises.",
  INJURY_PLAYER_STATUS_OR_SOURCE_MISSING: "Une indisponibilité sourcée est requise avant l’heure limite.",
  EXACTLY_TWO_COMPLETE_ELEVEN_PLAYER_LINEUPS_REQUIRED: "Deux compositions complètes de onze joueurs sont requises.",
  EXACT_ODDS_BOOKMAKER_MARGIN_OR_OBSERVED_AT_MISSING: "La cote, le bookmaker, la marge et l’heure d’observation doivent être prouvés.",
  NO_FIXTURE: "Aucune rencontre active n’est disponible.",
};

const hypothesisMechanisms: Record<string, string> = {
  "H11-001": "Une attaque en forme pourrait profiter d’une défense centrale remaniée.",
  "H11-002": "La structure du milieu pourrait créer un surnombre ou exposer les couloirs.",
  "H11-003": "L’orientation des appuis peut modifier la qualité des duels sur un côté.",
  "H11-004": "L’absence du gardien habituel peut modifier l’organisation défensive.",
  "H11-005": "Un duo central peu habitué à jouer ensemble peut manquer de coordination.",
  "H11-006": "La stabilité de l’équipe de départ peut améliorer les automatismes.",
  "H11-007": "Un calendrier dense peut favoriser une formation ou une rotation inhabituelle.",
  "H11-008": "Certaines structures tactiques peuvent se neutraliser ou créer un avantage local.",
};

function record(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

function records(value: unknown): UnknownRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value ? value : fallback;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanValue(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function validDate(value: string): boolean {
  return Boolean(value) && Number.isFinite(new Date(value).getTime());
}

function activeFixture(item: UnknownRecord): boolean {
  const status = text(item.status, "REGISTERED");
  return (
    !booleanValue(item.cancelled) &&
    !["CANCELLED", "CANCELED", "TOMBSTONED", "DELETED"].includes(status)
  );
}

function fixtureName(item: UnknownRecord, side: "home" | "away"): string {
  const name = optionalText(item[`${side}_name`]);
  if (name) return name;
  return "Équipe en cours d’identification";
}

function fixtureIdentitySource(
  item: UnknownRecord,
  side: "home" | "away",
): string | null {
  return optionalText(record(item[`${side}_identity_provenance`]).source);
}

function presentationWindow(item: UnknownRecord): PresentationWindow | null {
  const id = text(item.window_id);
  const fixtureId = text(item.fixture_id);
  const dueAt = text(item.due_at);
  const opensAt = text(item.opens_at, dueAt);
  const cutoffAt = text(item.cutoff_at, dueAt);
  const kickoffAt = text(item.kickoff_at, cutoffAt);
  if (
    !id ||
    !fixtureId ||
    !validDate(opensAt) ||
    !validDate(dueAt) ||
    !validDate(cutoffAt) ||
    !validDate(kickoffAt)
  ) {
    return null;
  }
  return {
    id,
    fixtureId,
    family: text(item.family),
    label: text(item.label),
    opensAt,
    dueAt,
    cutoffAt,
    kickoffAt,
    status: text(item.status, "NOT_DUE"),
    active: booleanValue(item.active, true),
    acknowledged: booleanValue(item.acknowledged),
    policyVersion: text(item.policy_version),
  };
}

function currentWindowStatus(
  window: PresentationWindow,
  now: Date,
): string {
  if (window.acknowledged || ["COMPLETE", "CAPTURED", "CAPTURED_EMPTY"].includes(window.status)) {
    return "COMPLETE";
  }
  const current = now.getTime();
  if (current < new Date(window.opensAt).getTime()) return "NOT_DUE";
  if (current < new Date(window.cutoffAt).getTime()) return "DUE";
  return "MISSED_WINDOW";
}

function collectStatusValues(value: unknown, output = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectStatusValues(item, output);
    return output;
  }
  if (value === null || typeof value !== "object") return output;
  for (const [key, child] of Object.entries(value as UnknownRecord)) {
    if (
      typeof child === "string" &&
      (/(?:^|_)status$/i.test(key) || /Status$/.test(key))
    ) {
      output.add(child);
    }
    collectStatusValues(child, output);
  }
  return output;
}

function freshnessModel(
  snapshot: UnknownRecord,
  observatory: UnknownRecord,
  windows: PresentationWindow[],
  validationErrors: string[],
  now: Date,
): FreshnessPresentation {
  const generatedAt = text(
    observatory.generated_at,
    text(snapshot.generatedAt),
  );
  const generatedTime = new Date(generatedAt).getTime();
  const ageMinutes = Number.isFinite(generatedTime)
    ? Math.max(0, Math.floor((now.getTime() - generatedTime) / 60_000))
    : null;
  const runs = records(snapshot.runs);
  const lastWorkflowAt = runs
    .map((run) => text(run.finishedAt))
    .filter(validDate)
    .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null;

  if (!generatedAt || ageMinutes === null || validationErrors.length) {
    return {
      status: "FRESHNESS_INVALID",
      generatedAt,
      ageMinutes,
      reason: validationErrors[0] ?? "La date de génération du snapshot est invalide.",
      threshold: "Schéma valide et horodatage UTC requis.",
      lastWorkflowAt,
    };
  }

  const source = record(observatory.source);
  if (text(source.refresh_status) === "IN_PROGRESS") {
    return {
      status: "FRESHNESS_UPDATING",
      generatedAt,
      ageMinutes,
      reason: "Un workflow de snapshot est signalé comme étant en cours.",
      threshold: "Le dernier snapshot valide reste affiché pendant l’actualisation.",
      lastWorkflowAt,
    };
  }

  const expectedSinceSnapshot = windows.filter((window) => {
    if (!window.active || window.acknowledged) return false;
    const opensAt = new Date(window.opensAt).getTime();
    return opensAt > generatedTime && opensAt <= now.getTime();
  });
  if (expectedSinceSnapshot.length) {
    return {
      status: "FRESHNESS_STALE",
      generatedAt,
      ageMinutes,
      reason: `${expectedSinceSnapshot.length} fenêtre${expectedSinceSnapshot.length > 1 ? "s" : ""} de capture se sont ouvertes depuis la génération.`,
      threshold: "Actualisation attendue dans l’heure suivant l’ouverture d’une fenêtre.",
      lastWorkflowAt,
    };
  }

  return {
    status: "FRESHNESS_CURRENT",
    generatedAt,
    ageMinutes,
    reason: "Aucune nouvelle fenêtre de capture n’était attendue depuis ce snapshot.",
    threshold: "24 h hors fenêtre ; 1 h lorsqu’une fenêtre est ouverte.",
    lastWorkflowAt,
  };
}

export function buildPresentationModel(
  input: unknown,
  options: { now?: Date } = {},
): PresentationModel {
  const snapshot = record(input);
  const observatory = record(snapshot.prospectiveObservatory);
  const fixtureRoot = record(observatory.fixtures);
  const windowRoot = record(observatory.windows);
  const captureRoot = record(observatory.captures);
  const r2 = record(observatory.r2);
  const postgresql = record(observatory.postgresql);
  const ledger = record(observatory.ledger);
  const providers = record(observatory.providers);
  const source = record(observatory.source);
  const now = options.now ?? new Date();

  const validationErrors: string[] = [];
  if (!text(observatory.schema_version)) {
    validationErrors.push("Version de schéma prospective absente.");
  }

  const rawFixtures = records(fixtureRoot.registry);
  const seenFixtures = new Set<string>();
  for (const fixture of rawFixtures) {
    const fixtureId = text(fixture.fixture_id);
    if (!fixtureId || seenFixtures.has(fixtureId)) {
      validationErrors.push("Clé canonique de fixture absente ou dupliquée.");
    }
    seenFixtures.add(fixtureId);
    if (!validDate(text(fixture.kickoff_at))) {
      validationErrors.push(`Kickoff invalide pour ${fixtureId || "fixture inconnue"}.`);
    }
  }
  const activeFixtures = rawFixtures.filter(activeFixture);
  const activeFixtureIds = new Set(activeFixtures.map((item) => text(item.fixture_id)));

  const windows = records(windowRoot.registry)
    .map(presentationWindow)
    .filter((item): item is PresentationWindow => item !== null);
  if (windows.length !== records(windowRoot.registry).length) {
    validationErrors.push("Une fenêtre de capture possède des bornes invalides.");
  }
  for (const window of windows) {
    if (!activeFixtureIds.has(window.fixtureId) && window.active) {
      validationErrors.push(`Fenêtre active sans fixture active : ${window.id}.`);
    }
  }

  const evidence = records(fixtureRoot.evidence);
  const hypotheses = records(observatory.hypotheses).map((item) => ({
    id: text(item.id),
    title: text(item.title, "Hypothèse football"),
    mechanism: hypothesisMechanisms[text(item.id)] ?? "Mécanisme à vérifier prospectivement.",
    requiredData: stringList(item.required_data),
    minimumSupport: numberValue(item.minimum_support),
    observations: numberValue(item.observations),
    coverage: numberValue(item.coverage),
    status: text(item.status, "WAITING_FOR_OBSERVATIONS"),
    frozen: booleanValue(item.frozen),
  }));

  const oddsSnapshots = records(observatory.odds).map((item, index) => {
    const probabilities = record(item.probabilities);
    return {
      id: text(item.snapshot_id, text(item.id, `snapshot-${index}`)),
      fixtureId: text(item.fixture_id),
      observedAt: text(item.observed_at),
      provider: text(item.provider),
      bookmakers: numberValue(item.bookmakers),
      quotes: numberValue(item.quotes),
      markets: stringList(item.markets),
      hash: text(item.payload_hash),
      probabilities: {
        home: optionalNumber(probabilities.home),
        draw: optionalNumber(probabilities.draw),
        away: optionalNumber(probabilities.away),
      },
    };
  });

  const matches = activeFixtures
    .map((fixture): MatchPresentation => {
      const fixtureId = text(fixture.fixture_id);
      const fixtureEvidence = evidence.filter(
        (item) => text(item.fixture_id) === fixtureId,
      );
      const fixtureWindows = windows
        .filter((window) => window.fixtureId === fixtureId && window.active)
        .map((window) => ({ ...window, status: currentWindowStatus(window, now) }))
        .sort((left, right) => new Date(left.opensAt).getTime() - new Date(right.opensAt).getTime());
      const eligibleWindows = fixtureWindows.filter(
        (window) => !["COMPLETE", "MISSED_WINDOW"].includes(window.status),
      );
      const nextWindow = eligibleWindows[0] ?? null;
      const nextFamilies = nextWindow
        ? Array.from(
            new Set(
              eligibleWindows
                .filter((window) => window.dueAt === nextWindow.dueAt)
                .map((window) => window.family),
            ),
          )
        : [];
      const capturedFamilies = new Set(
        fixtureEvidence
          .filter((item) => ["CAPTURED", "COMPLETE"].includes(text(item.status)))
          .map((item) => text(item.family)),
      );
      const emptyFamilies = new Set(
        fixtureEvidence
          .filter((item) => text(item.status) === "CAPTURED_EMPTY")
          .map((item) => text(item.family)),
      );
      const erroredFamilies = new Set(
        fixtureEvidence
          .filter((item) => ["ERROR", "INVALID_PAYLOAD", "TEMPORALITY_FAILED"].includes(text(item.status)))
          .map((item) => text(item.family)),
      );
      const families = Object.fromEntries(
        displayedFamilies.map((family): [string, CoverageState] => {
          if (capturedFamilies.has(family)) return [family, "captured"];
          if (emptyFamilies.has(family)) return [family, "empty"];
          if (erroredFamilies.has(family)) return [family, "error"];
          const familyWindows = fixtureWindows.filter((item) => item.family === family);
          if (familyWindows.some((item) => item.status === "MISSED_WINDOW")) {
            return [family, "late"];
          }
          return [family, familyWindows.length ? "upcoming" : "blocked"];
        }),
      );
      const matchOdds = oddsSnapshots.filter((item) => item.fixtureId === fixtureId);
      const latestOdds = matchOdds.at(-1);
      const availableFamilies = Object.values(families).filter(
        (state) => state === "captured" || state === "empty",
      ).length;
      return {
        id: fixtureId,
        providerId: fixtureId,
        internalId: text(fixture.canonical_key, fixtureId),
        competition: text(fixture.competition, "Compétition non renseignée"),
        home: fixtureName(fixture, "home"),
        away: fixtureName(fixture, "away"),
        homeTeamId: text(fixture.home_team_id, text(fixture.home)),
        awayTeamId: text(fixture.away_team_id, text(fixture.away)),
        homeIdentityStatus: text(fixture.home_identity_status, "UNRESOLVED"),
        awayIdentityStatus: text(fixture.away_identity_status, "UNRESOLVED"),
        homeIdentitySource: fixtureIdentitySource(fixture, "home"),
        awayIdentitySource: fixtureIdentitySource(fixture, "away"),
        kickoff: text(fixture.kickoff_at),
        matchStatus: text(fixture.status, "REGISTERED"),
        dataStatus: matchOdds.length || availableFamilies > 1
          ? "PARTIAL"
          : "WAITING_FOR_OBSERVATIONS",
        coverage: displayedFamilies.length
          ? availableFamilies / displayedFamilies.length
          : 0,
        nextCapture: nextWindow?.dueAt ?? null,
        nextFamily: nextWindow?.family ?? null,
        nextFamilies,
        observedOdds: matchOdds.length > 0,
        hypotheses: hypotheses.length,
        families,
        probabilities: latestOdds?.probabilities ?? {
          home: null,
          draw: null,
          away: null,
        },
        timeline: fixtureWindows.slice(0, 12),
      };
    })
    .sort((left, right) => new Date(left.kickoff).getTime() - new Date(right.kickoff).getTime());

  const matchNames = new Map(
    matches.map((match) => [match.id, `${match.home} – ${match.away}`]),
  );
  const eligibleWindows = windows
    .filter((window) => window.active && activeFixtureIds.has(window.fixtureId))
    .map((window) => ({ ...window, status: currentWindowStatus(window, now) }))
    .filter((window) => !["COMPLETE", "MISSED_WINDOW"].includes(window.status))
    .sort((left, right) => new Date(left.dueAt).getTime() - new Date(right.dueAt).getTime());
  const captureGroups = new Map<string, PresentationWindow[]>();
  for (const window of eligibleWindows) {
    captureGroups.set(window.dueAt, [
      ...(captureGroups.get(window.dueAt) ?? []),
      window,
    ]);
  }
  const nextCaptures = [...captureGroups.entries()].map(
    ([dueAt, group]): NextCapturePresentation => {
      const fixtureIds = Array.from(new Set(group.map((item) => item.fixtureId)));
      const families = Array.from(new Set(group.map((item) => item.family)));
      return {
        id: `capture-group:${dueAt}`,
        dueAt,
        opensAt: group.reduce(
          (earliest, item) =>
            new Date(item.opensAt).getTime() < new Date(earliest).getTime()
              ? item.opensAt
              : earliest,
          group[0].opensAt,
        ),
        cutoffAt: group.reduce(
          (latest, item) =>
            new Date(item.cutoffAt).getTime() > new Date(latest).getTime()
              ? item.cutoffAt
              : latest,
          group[0].cutoffAt,
        ),
        match: fixtureIds.length === 1
          ? matchNames.get(fixtureIds[0]) ?? "Rencontre concernée"
          : `${fixtureIds.length} rencontres concernées`,
        fixtureCount: fixtureIds.length,
        fixtureIds,
        family: families[0],
        families,
        status: group.some((item) => item.status === "DUE") ? "DUE" : "NOT_DUE",
      };
    },
  );
  const competitionRows = records(observatory.competitions);
  const leagueRows: UnknownRecord[] = competitionRows.length
    ? competitionRows
    : Array.from(new Set(matches.map((match) => match.competition))).map(
      (competition) => ({
        competition,
        capture_profile: "FULL",
        fixtures: matches.filter((match) => match.competition === competition).length,
        teams: new Set(
          matches
            .filter((match) => match.competition === competition)
            .flatMap((match) => [match.homeTeamId, match.awayTeamId]),
        ).size,
        gate: "BLOCKED_PROVIDER",
      }),
    );
  const leagues = leagueRows.map(
    (item): LeaguePresentation => {
      const competition = text(item.competition, "Compétition non renseignée");
      const scopedMatches = matches.filter(
        (match) => match.competition === competition,
      );
      const coverage = scopedMatches.length
        ? scopedMatches.reduce((sum, match) => sum + match.coverage, 0)
          / scopedMatches.length
        : 0;
      return {
        competition,
        captureProfile: text(item.capture_profile, "DISABLED"),
        fixtures: numberValue(item.fixtures),
        teams: numberValue(item.teams),
        identitySlotsVerified: numberValue(item.identity_slots_verified),
        identitySlotsExpected: numberValue(item.identity_slots_expected),
        activeWindows: numberValue(item.windows),
        nextCaptures: numberValue(item.next_captures),
        captures: numberValue(item.captures),
        deepObservations: numberValue(item.deep_observations),
        emptyResponses: numberValue(item.empty_responses),
        apiFootballCalls: numberValue(item.api_football_calls),
        oddsApiCredits: numberValue(item.odds_api_credits),
        gate: text(item.gate, "BLOCKED_PROVIDER"),
        r2: text(item.r2, "PENDING"),
        postgresql: text(item.postgresql, "PENDING"),
        replay: text(item.replay, "PENDING"),
        coverage,
      };
    },
  );

  const gateRows = Object.entries(record(record(observatory.gates).by_name)).map(
    ([technicalName, raw]) => {
      const gate = record(raw);
      const reason = text(gate.reason, "NO_FIXTURE");
      return {
        name: gateNames[technicalName] ?? technicalName,
        technicalName,
        status: text(gate.status, "WAITING_FOR_OBSERVATIONS"),
        passed: numberValue(gate.passed),
        total: numberValue(gate.total),
        reason: reason
          .split(",")
          .map((item) => gateReasons[item] ?? "La vérification attend encore une preuve complète.")
          .join(" "),
      };
    },
  );

  const freshness = freshnessModel(
    snapshot,
    observatory,
    windows,
    validationErrors,
    now,
  );
  const statuses = [...collectStatusValues(snapshot)].sort();
  const unknownStatuses = statuses.filter((status) => !(status in statusCatalogue));
  const statusCoverage = {
    total: statuses.length,
    translated: statuses.length - unknownStatuses.length,
    percentage: statuses.length
      ? (statuses.length - unknownStatuses.length) / statuses.length
      : 1,
    unknown: unknownStatuses,
  };

  const captureFamilies = record(captureRoot.by_family);
  const deepFamilies = [
    "SQUAD",
    "PLAYER_STATUS",
    "INJURY",
    "LINEUP",
    "FORMATION",
    "ODDS",
  ];
  const patternResearch = record(snapshot.patternResearch);
  const bankroll = record(patternResearch.bankroll);
  const operationalEvidence: OperationalEvidence = {
    generatedAt: freshness.generatedAt,
    sourceRun: text(source.run_id, "Non disponible"),
    sourceRevision: text(source.revision, "Non disponible"),
    sourceWorkflow: text(source.workflow, "Non disponible"),
    status: text(observatory.status, "FRESHNESS_INVALID"),
    origin: text(observatory.origin, "NO_OUTPUT"),
    fixtures: matches.length,
    activeWindows: windows.filter(
      (window) => window.active && activeFixtureIds.has(window.fixtureId),
    ).length,
    inactiveLegacyWindows: numberValue(windowRoot.inactive_legacy),
    dueWindows: windows.filter(
      (window) =>
        window.active &&
        activeFixtureIds.has(window.fixtureId) &&
        currentWindowStatus(window, now) === "DUE",
    ).length,
    physicalEvidence: numberValue(r2.objects_added),
    fixtureCaptures: numberValue(record(captureFamilies.FIXTURE).captured),
    deepObservations: deepFamilies.reduce(
      (sum, family) => sum + numberValue(record(captureFamilies[family]).captured),
      0,
    ),
    emptyResponses: numberValue(captureRoot.empty),
    errors: numberValue(providers.errors) + numberValue(captureRoot.invalid),
    delays: numberValue(record(observatory.temporal).late),
    candidates: numberValue(observatory.candidates),
    decisions: numberValue(observatory.decisions),
    r2: {
      objects: numberValue(r2.objects_added),
      bytes: numberValue(r2.bytes),
      verified: numberValue(r2.verified),
      lag: numberValue(r2.lag),
      deletions: numberValue(r2.deletions),
      replayStatus: text(r2.replay_status, "NOT_RUN_NO_CAPTURE"),
    },
    postgresql: {
      migration: text(postgresql.migration, "Non disponible"),
      tables: numberValue(postgresql.tables),
      inserts: numberValue(postgresql.inserts),
      duplicatesAvoided: numberValue(postgresql.duplicates_avoided),
      lag: numberValue(postgresql.lag),
      reconstructionStatus: text(postgresql.reconstruction_status, "NOT_RUN_NO_CAPTURE"),
      payloadBodyRows: numberValue(postgresql.payload_body_rows),
    },
    ledger: {
      events: numberValue(ledger.events),
      headHash: text(ledger.head_hash, "Non disponible"),
    },
    providers: {
      apiFootballCalls: numberValue(providers.api_football_calls),
      oddsApiCredits: numberValue(providers.odds_api_credits),
      apiFootballCap: numberValue(record(providers.budgets).api_football_max_total),
      oddsApiCap: numberValue(record(providers.budgets).odds_api_max_total),
    },
    invariants: Object.fromEntries(
      Object.entries(record(observatory.invariants)).filter(
        ([, value]) => ["boolean", "string", "number"].includes(typeof value),
      ),
    ) as Record<string, boolean | string | number>,
    freshness,
  };

  return {
    dashboard: {
      operationalEvidence,
      bankroll: {
        initialUnits: optionalNumber(bankroll.initialUnits),
        currentUnits: optionalNumber(bankroll.currentUnits),
        policySource: optionalText(bankroll.policySource),
      },
    },
    matches,
    leagues,
    nextCaptures,
    observatory: { gateRows },
    hypotheses,
    results: patternResearch,
    expert: {
      deepData: record(snapshot.deepData),
      qualityChecks: records(snapshot.qualityChecks),
      providers: record(snapshot.providers),
      incidents: records(snapshot.incidents),
      quota: record(snapshot.quota),
      provenance: record(snapshot.provenance),
      matchup: record(snapshot.matchupLab),
      patternResearch,
    },
    system: {
      freshness,
      statusCoverage,
      encodingCorrections: {
        count: 0,
        fields: [],
        cleanerEnabled: false,
      },
      validationErrors,
    },
    oddsSnapshots,
  };
}
