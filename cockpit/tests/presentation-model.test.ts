import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { buildPresentationModel } from "../app/lib/presentation-model";
import { statusPresentation } from "../app/i18n/status-translations";

type MutableRecord = Record<string, unknown>;

type TestFixture = MutableRecord & {
  fixture_id: string;
  kickoff_at: string;
};

type TestWindow = MutableRecord & {
  window_id: string;
  fixture_id: string;
  opens_at: string;
  due_at: string;
  cutoff_at: string;
  kickoff_at: string;
};

type TestSnapshot = MutableRecord & {
  prospectiveObservatory: MutableRecord & {
    generated_at: string;
    competitions?: MutableRecord[];
    r2: MutableRecord & {
      objects_added: number;
      verified: number;
    };
    captures: MutableRecord & {
      captured: number;
      by_family: Record<string, MutableRecord & {
        captured: number;
        hashes: number;
      }>;
    };
    fixtures: MutableRecord & {
      registry: TestFixture[];
      evidence: MutableRecord[];
      tracked: number;
    };
    windows: MutableRecord & {
      registry: TestWindow[];
      next: TestWindow[];
      planned: number;
    };
    gates: {
      by_name: Record<string, MutableRecord>;
    };
    odds?: MutableRecord[];
    candidates: number;
    decisions: number;
  };
  patternResearch: MutableRecord & {
    dataStatus: string;
    ledger: MutableRecord;
    bankroll: MutableRecord;
    results: MutableRecord;
  };
};

const snapshot = JSON.parse(
  await readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
) as TestSnapshot;

const referenceNow = new Date("2026-07-28T12:00:00+00:00");

function cloneSnapshot(): TestSnapshot {
  return structuredClone(snapshot) as TestSnapshot;
}

function shiftIso(value: string, milliseconds: number): string {
  return new Date(new Date(value).getTime() + milliseconds).toISOString();
}

function addSyntheticFixture(
  value: TestSnapshot,
  {
    fixtureId,
    kickoffShift,
  }: {
    fixtureId: string;
    kickoffShift: number;
  },
) {
  const fixtures = value.prospectiveObservatory.fixtures.registry;
  const windows = value.prospectiveObservatory.windows.registry;
  const source = fixtures[0];
  const sourceWindows = windows.filter(
    (window) => window.fixture_id === source.fixture_id,
  );
  fixtures.push({
    ...structuredClone(source),
    fixture_id: fixtureId,
    canonical_key: fixtureId,
    provider: "synthetic-test",
    provider_fixture_id: fixtureId.split(":").at(-1),
    home_team_id: "test-home",
    away_team_id: "test-away",
    home_name: "Équipe Test Domicile",
    away_name: "Équipe Test Extérieure",
    kickoff_at: shiftIso(source.kickoff_at, kickoffShift),
    lifecycle_version_hash: null,
  });
  windows.push(
    ...sourceWindows.map((window, index) => ({
      ...structuredClone(window),
      window_id: `synthetic-window:${fixtureId}:${index}`,
      fixture_id: fixtureId,
      opens_at: shiftIso(window.opens_at, kickoffShift),
      due_at: shiftIso(window.due_at, kickoffShift),
      cutoff_at: shiftIso(window.cutoff_at, kickoffShift),
      kickoff_at: shiftIso(window.kickoff_at, kickoffShift),
    })),
  );
  value.prospectiveObservatory.windows.planned = windows.length;
}

test("cas A — le modèle reflète le snapshot réel sans constante frontend", () => {
  const model = buildPresentationModel(snapshot, { now: referenceNow });
  const activeFixtureIds = new Set(
    snapshot.prospectiveObservatory.fixtures.registry
      .filter(
        (fixture) =>
          fixture.cancelled !== true &&
          !["CANCELLED", "CANCELED", "TOMBSTONED", "DELETED"].includes(
            String(fixture.status),
          ),
      )
      .map((fixture) => fixture.fixture_id),
  );
  const activeWindows = snapshot.prospectiveObservatory.windows.registry.filter(
    (window) =>
      window.active !== false && activeFixtureIds.has(window.fixture_id),
  ).length;
  const captureFamilies = snapshot.prospectiveObservatory.captures.by_family;
  const deepObservations = [
    "SQUAD",
    "PLAYER_STATUS",
    "INJURY",
    "LINEUP",
    "FORMATION",
    "ODDS",
  ].reduce(
    (sum, family) => sum + Number(captureFamilies[family]?.captured ?? 0),
    0,
  );
  assert.equal(model.matches.length, activeFixtureIds.size);
  assert.equal(model.dashboard.operationalEvidence.activeWindows, activeWindows);
  assert.equal(
    model.dashboard.operationalEvidence.physicalEvidence,
    snapshot.prospectiveObservatory.r2.objects_added,
  );
  assert.equal(
    model.dashboard.operationalEvidence.deepObservations,
    deepObservations,
  );
  assert.equal(
    model.dashboard.bankroll.currentUnits,
    snapshot.patternResearch.bankroll.currentUnits,
  );
  assert.equal(model.system.freshness.status, "FRESHNESS_CURRENT");
});

test("cas B — une capture et un gate évoluent par mutation du snapshot seul", () => {
  const value = cloneSnapshot();
  const observatory = value.prospectiveObservatory;
  const fixtureId = observatory.fixtures.registry[0].fixture_id;
  observatory.r2.objects_added = 19;
  observatory.r2.verified = 19;
  observatory.captures.captured += 1;
  observatory.captures.by_family.INJURY.captured = 1;
  observatory.captures.by_family.INJURY.hashes = 1;
  observatory.fixtures.evidence.push({
    fixture_id: fixtureId,
    family: "INJURY",
    status: "CAPTURED",
    observed_at: observatory.generated_at,
    response_received_at: observatory.generated_at,
    window_id: null,
    temporally_admissible: true,
    provenance: "SYNTHETIC_TEST_ONLY",
  });
  observatory.gates.by_name.PROSPECTIVE_INJURY_GATE.passed = 1;

  const model = buildPresentationModel(value, { now: referenceNow });
  assert.equal(model.dashboard.operationalEvidence.physicalEvidence, 19);
  assert.equal(model.dashboard.operationalEvidence.deepObservations, 1);
  assert.equal(
    model.matches.find((match) => match.id === fixtureId)?.families.INJURY,
    "captured",
  );
  assert.equal(
    model.observatory.gateRows.find(
      (gate) => gate.technicalName === "PROSPECTIVE_INJURY_GATE",
    )?.passed,
    1,
  );
});

test("cas C — une dixième fixture apparaît automatiquement", () => {
  const value = cloneSnapshot();
  const initialFixtureCount = value.prospectiveObservatory.fixtures.registry.length;
  addSyntheticFixture(value, {
    fixtureId: "synthetic-test:fixture-10",
    kickoffShift: 7 * 86_400_000,
  });
  const model = buildPresentationModel(value, { now: referenceNow });
  assert.equal(model.matches.length, initialFixtureCount + 1);
  assert.ok(model.matches.some((match) => match.id === "synthetic-test:fixture-10"));
});

test("cinq ligues — les profils et gates restent pilotés par le snapshot", () => {
  const value = cloneSnapshot();
  value.prospectiveObservatory.competitions = [
    {
      competition: "Ligue 1",
      capture_profile: "FULL",
      fixtures: 9,
      teams: 18,
      identity_slots_verified: 18,
      identity_slots_expected: 18,
      windows: 441,
      next_captures: 9,
      captures: 18,
      deep_observations: 0,
      empty_responses: 0,
      api_football_calls: 3,
      odds_api_credits: 0,
      gate: "ACTIVE_FULL",
      r2: "VERIFIED",
      postgresql: "VERIFIED",
      replay: "VERIFIED",
    },
    ...["Premier League", "Liga", "Bundesliga", "Serie A"].map(
      (competition) => ({
        competition,
        capture_profile: "DEEP_FULL_ODDS_REDUCED",
        fixtures: 0,
        teams: 0,
        identity_slots_verified: 0,
        identity_slots_expected: 0,
        windows: 0,
        next_captures: 0,
        captures: 0,
        deep_observations: 0,
        empty_responses: 0,
        api_football_calls: 3,
        odds_api_credits: 0,
        gate: "BLOCKED_PROVIDER",
        r2: "PENDING",
        postgresql: "PENDING",
        replay: "PENDING",
      }),
    ),
  ];

  const model = buildPresentationModel(value, { now: referenceNow });
  assert.deepEqual(
    model.leagues.map((league) => league.competition),
    ["Ligue 1", "Premier League", "Liga", "Bundesliga", "Serie A"],
  );
  assert.equal(model.leagues[0].captureProfile, "FULL");
  assert.equal(model.leagues[0].gate, "ACTIVE_FULL");
  assert.equal(
    model.leagues[1].captureProfile,
    "DEEP_FULL_ODDS_REDUCED",
  );
  assert.equal(model.leagues[1].gate, "BLOCKED_PROVIDER");
});

test("identité A — un nom vérifié du snapshot est affiché tel quel", () => {
  const value = cloneSnapshot();
  const fixture = value.prospectiveObservatory.fixtures.registry[0];
  fixture.home_name = "Olympique Synthétique Vérifié";
  fixture.home_identity_status = "VERIFIED";
  fixture.home_identity_provenance = { source: "R2_FIXTURE_PAYLOAD" };
  const match = buildPresentationModel(value, { now: referenceNow }).matches[0];
  assert.equal(match.home, "Olympique Synthétique Vérifié");
  assert.equal(match.homeIdentityStatus, "VERIFIED");
  assert.equal(match.homeIdentitySource, "R2_FIXTURE_PAYLOAD");
});

test("identité B — une identité absente masque l’identifiant en vue essentielle", () => {
  const value = cloneSnapshot();
  const fixture = value.prospectiveObservatory.fixtures.registry[0];
  fixture.home_name = null;
  fixture.home_identity_status = "UNRESOLVED";
  fixture.home_identity_provenance = null;
  const match = buildPresentationModel(value, { now: referenceNow }).matches[0];
  assert.equal(match.home, "Équipe en cours d’identification");
  assert.equal(match.homeTeamId, fixture.home_team_id);
  assert.equal(match.homeIdentityStatus, "UNRESOLVED");
  assert.doesNotMatch(match.home, new RegExp(String(fixture.home_team_id)));
});

test("identité C — une nouvelle équipe apparaît sans modification frontend", () => {
  const value = cloneSnapshot();
  addSyntheticFixture(value, {
    fixtureId: "synthetic-test:new-team-identity",
    kickoffShift: 8 * 86_400_000,
  });
  const match = buildPresentationModel(value, { now: referenceNow }).matches.find(
    (item) => item.id === "synthetic-test:new-team-identity",
  );
  assert.equal(match?.home, "Équipe Test Domicile");
  assert.equal(match?.away, "Équipe Test Extérieure");
});

test("cas D — le report d’un match déplace kickoff et fenêtres", () => {
  const value = cloneSnapshot();
  const fixture = value.prospectiveObservatory.fixtures.registry[0];
  const homeName = fixture.home_name;
  const awayName = fixture.away_name;
  const originalKickoff = fixture.kickoff_at;
  const originalNext = value.prospectiveObservatory.windows.registry
    .filter((window) => window.fixture_id === fixture.fixture_id)
    .sort((left, right) =>
      left.opens_at.localeCompare(right.opens_at),
    )[0].due_at;
  const shift = 24 * 3_600_000;
  fixture.kickoff_at = shiftIso(fixture.kickoff_at, shift);
  const temporalFields = [
    "opens_at",
    "due_at",
    "cutoff_at",
    "kickoff_at",
  ] as const;
  for (const window of value.prospectiveObservatory.windows.registry) {
    if (window.fixture_id !== fixture.fixture_id) continue;
    for (const field of temporalFields) {
      window[field] = shiftIso(window[field], shift);
    }
  }

  const model = buildPresentationModel(value, { now: referenceNow });
  const match = model.matches.find((item) => item.id === fixture.fixture_id);
  assert.equal(match?.kickoff, shiftIso(originalKickoff, shift));
  assert.equal(match?.nextCapture, shiftIso(originalNext, shift));
  assert.equal(match?.home, homeName ?? "Équipe en cours d’identification");
  assert.equal(match?.away, awayName ?? "Équipe en cours d’identification");
});

test("identité G — réordonner les fixtures ne change aucune association", () => {
  const value = cloneSnapshot();
  const expected = new Map(
    buildPresentationModel(value, { now: referenceNow }).matches.map((match) => [
      match.id,
      `${match.home}|${match.away}`,
    ]),
  );
  value.prospectiveObservatory.fixtures.registry.reverse();
  const reordered = buildPresentationModel(value, { now: referenceNow });
  assert.deepEqual(
    new Map(reordered.matches.map((match) => [match.id, `${match.home}|${match.away}`])),
    expected,
  );
});

test("cas E — une cote prospective capturée apparaît sans code par match", () => {
  const value = cloneSnapshot();
  const fixtureId = value.prospectiveObservatory.fixtures.registry[0].fixture_id;
  value.prospectiveObservatory.odds = [
    {
      snapshot_id: "synthetic-odds-1",
      fixture_id: fixtureId,
      observed_at: value.prospectiveObservatory.generated_at,
      provider: "synthetic-test",
      bookmakers: 2,
      quotes: 6,
      markets: ["1X2"],
      payload_hash: "synthetic-test-hash",
      probabilities: { home: 0.5, draw: 0.3, away: 0.2 },
    },
  ];
  const model = buildPresentationModel(value, { now: referenceNow });
  const match = model.matches.find((item) => item.id === fixtureId);
  assert.equal(match?.observedOdds, true);
  assert.equal(match?.probabilities.home, 0.5);
  assert.equal(model.oddsSnapshots.length, 1);
});

test("cas F — zéro fixture produit un état vide stable", () => {
  const value = cloneSnapshot();
  value.prospectiveObservatory.fixtures.registry = [];
  value.prospectiveObservatory.fixtures.evidence = [];
  value.prospectiveObservatory.fixtures.tracked = 0;
  value.prospectiveObservatory.windows.registry = [];
  value.prospectiveObservatory.windows.next = [];
  value.prospectiveObservatory.windows.planned = 0;
  const model = buildPresentationModel(value, { now: referenceNow });
  assert.deepEqual(model.matches, []);
  assert.deepEqual(model.nextCaptures, []);
  assert.equal(model.dashboard.operationalEvidence.fixtures, 0);
});

test("cas G — une décision shadow future dérive résultats et bankroll", () => {
  const value = cloneSnapshot();
  value.prospectiveObservatory.candidates = 1;
  value.prospectiveObservatory.decisions = 1;
  value.patternResearch.dataStatus = "LIVE_SHADOW_LEDGER";
  value.patternResearch.ledger.decisions = 1;
  value.patternResearch.ledger.records = 1;
  value.patternResearch.bankroll.currentUnits = 1002;
  value.patternResearch.bankroll.profitUnits = 2;
  value.patternResearch.bankroll.curve = [1000, 1002];
  value.patternResearch.results.profitUnits = 2;
  value.patternResearch.results.settlements = 1;
  value.patternResearch.results.settledStakeUnits = 10;
  value.patternResearch.results.roi = 0.2;

  const model = buildPresentationModel(value, { now: referenceNow });
  assert.equal(model.dashboard.operationalEvidence.candidates, 1);
  assert.equal(model.dashboard.operationalEvidence.decisions, 1);
  assert.equal(model.dashboard.bankroll.currentUnits, 1002);
  assert.equal((model.results.results as MutableRecord).profitUnits, 2);
  assert.equal((model.results.results as MutableRecord).roi, 0.2);
});

test("les captures simultanées regroupent les rencontres sans choisir la première", () => {
  const model = buildPresentationModel(snapshot, { now: referenceNow });
  const simultaneous = model.nextCaptures.find((capture) => capture.fixtureCount > 1);
  assert.ok(simultaneous);
  assert.equal(simultaneous.match, `${simultaneous.fixtureCount} rencontres concernées`);
});

test("la fraîcheur devient ancienne lorsqu’une fenêtre s’ouvre après le snapshot", () => {
  const model = buildPresentationModel(snapshot, {
    now: new Date("2026-08-01T18:00:00+00:00"),
  });
  assert.equal(model.system.freshness.status, "FRESHNESS_STALE");
  assert.match(model.system.freshness.reason, /fenêtre/);
});

test("tous les statuts du snapshot réel sont traduits", () => {
  const value = cloneSnapshot();
  value.prospectiveObservatory.postgresql = {
    ...(value.prospectiveObservatory.postgresql as MutableRecord),
    reconstruction_status:
      "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2",
  };
  const model = buildPresentationModel(value, { now: referenceNow });
  assert.equal(model.system.statusCoverage.percentage, 1);
  assert.deepEqual(model.system.statusCoverage.unknown, []);
});

test("un statut inconnu reste explicite et journalisé", () => {
  const warnings: string[] = [];
  const previous = console.warn;
  console.warn = (message?: unknown) => warnings.push(String(message));
  try {
    const presentation = statusPresentation("SYNTHETIC_UNKNOWN_STATUS");
    assert.equal(presentation.short, "État en cours de vérification");
    assert.match(presentation.long, /catalogue/);
    assert.equal(warnings.length, 1);
  } finally {
    console.warn = previous;
  }
});
