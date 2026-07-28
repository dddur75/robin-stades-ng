import snapshot from "../cockpit-data.json";

export const operationalEvidence = {
  generatedAt: "2026-07-27T23:47:02.391672+00:00",
  sourceRun: "jalon12-pilot-30314975830",
  sourceRevision: "2469e57ec4b2ef2849f9e707f63843033ec026e6",
  status: "PROSPECTIVE_GATES_ACCUMULATING",
  origin: "LIVE_PROSPECTIVE_CAPTURE",
  fixtures: 9,
  activeWindows: 441,
  inactiveLegacyWindows: 531,
  dueWindows: 0,
  physicalEvidence: 18,
  fixtureCaptures: 9,
  deepObservations: 0,
  emptyResponses: 0,
  errors: 0,
  delays: 0,
  candidates: 0,
  decisions: 0,
  r2: {
    objects: 18,
    bytes: 24_714,
    verified: 18,
    lag: 0,
    deletions: 0,
    replayStatus: "R2_REPLAY_VERIFIED",
  },
  postgresql: {
    migration: "0009_jalon12_observatory",
    tables: 12,
    inserts: 54,
    duplicatesAvoided: 9,
    lag: 0,
    reconstructionStatus: "RECONSTRUCTIBLE_FROM_R2",
    payloadBodyRows: 0,
  },
  ledger: {
    events: 586,
    headHash: "04395a33b7584d33a4413fb61dba41c3e7c4f83ef2e2e07fd2b16b0d116745c6",
  },
  providers: {
    apiFootballCalls: 0,
    oddsApiCredits: 0,
    apiFootballCap: 5_000,
    oddsApiCap: 250,
  },
  invariants: {
    STORAGE_PAUSED: true,
    P3_P4_PAUSED: true,
    PRODUCTION_LOCKED: true,
    REAL_BETS: false,
    NO_BET_DEFAULT: true,
    SOCIAL_PUBLISHING_ENABLED: false,
    DEMO_MODE_ENABLED: false,
  },
} as const;

const teamNamesByProviderId: Record<string, string> = {
  "81": "Marseille",
  "95": "Strasbourg",
  "116": "RC Lens",
  "108": "Auxerre",
  "1298": "Le Mans FC",
  "106": "Brest",
  "84": "Nice",
  "97": "Lorient",
  "96": "Toulouse",
  "80": "Lyon",
  "110": "Troyes",
  "114": "Paris FC",
  "77": "Angers",
  "79": "Lille",
  "111": "Le Havre",
  "91": "AS Monaco",
  "85": "Paris Saint-Germain",
  "94": "Rennes",
};

const providerFixtures = [
  { providerId: "api-football:1552733", home: "81", away: "95", kickoff: "2026-08-21T18:45:00+00:00" },
  { providerId: "api-football:1552732", home: "116", away: "108", kickoff: "2026-08-22T15:15:00+00:00" },
  { providerId: "api-football:1552731", home: "1298", away: "106", kickoff: "2026-08-22T18:45:00+00:00" },
  { providerId: "api-football:1552734", home: "84", away: "97", kickoff: "2026-08-22T18:45:00+00:00" },
  { providerId: "api-football:1552736", home: "96", away: "80", kickoff: "2026-08-22T18:45:00+00:00" },
  { providerId: "api-football:1552737", home: "110", away: "114", kickoff: "2026-08-22T18:45:00+00:00" },
  { providerId: "api-football:1552729", home: "77", away: "79", kickoff: "2026-08-23T13:00:00+00:00" },
  { providerId: "api-football:1552730", home: "111", away: "91", kickoff: "2026-08-23T15:15:00+00:00" },
  { providerId: "api-football:1552735", home: "85", away: "94", kickoff: "2026-08-23T18:45:00+00:00" },
] as const;

export type CoverageState = "captured" | "upcoming" | "empty" | "blocked" | "late" | "error";

export type MatchPresentation = {
  id: string;
  providerId: string;
  internalId: string;
  competition: string;
  home: string;
  away: string;
  kickoff: string;
  matchStatus: string;
  dataStatus: string;
  coverage: number;
  nextCapture: string;
  nextFamily: string;
  observedOdds: boolean;
  hypotheses: number;
  families: Record<string, CoverageState>;
  probabilities: { home: number | null; draw: number | null; away: number | null };
};

export const matches: MatchPresentation[] = providerFixtures.map((fixture, index) => {
  const legacyMatch = snapshot.matches[index];
  const observedOdds = index === 0 && snapshot.odds.length > 0;
  return {
    id: legacyMatch?.id ?? fixture.providerId.replace("api-football:", ""),
    providerId: fixture.providerId,
    internalId: legacyMatch?.internalId ?? "",
    competition: "Ligue 1",
    home: teamNamesByProviderId[fixture.home],
    away: teamNamesByProviderId[fixture.away],
    kickoff: fixture.kickoff,
    matchStatus: "REGISTERED",
    dataStatus: observedOdds ? "PARTIAL" : "WAITING_FOR_OBSERVATIONS",
    coverage: observedOdds ? 0.25 : 0.125,
    nextCapture: index === 0 ? "2026-07-31T18:45:00+00:00" : new Date(new Date(fixture.kickoff).getTime() - 21 * 86_400_000).toISOString(),
    nextFamily: "FIXTURE",
    observedOdds,
    hypotheses: 8,
    families: {
      FIXTURE: "captured",
      TEAM: "upcoming",
      SQUAD: "upcoming",
      PLAYER_STATUS: "upcoming",
      INJURY: "upcoming",
      LINEUP: "upcoming",
      FORMATION: "blocked",
      ODDS: observedOdds ? "captured" : "upcoming",
    },
    probabilities: {
      home: legacyMatch?.probabilities.home ?? null,
      draw: legacyMatch?.probabilities.draw ?? null,
      away: legacyMatch?.probabilities.away ?? null,
    },
  };
});

export const nextCaptures = matches.slice(0, 6).map((match) => ({
  id: `${match.providerId}-fixture`,
  dueAt: match.nextCapture,
  match: `${match.home} – ${match.away}`,
  family: match.nextFamily,
  status: "NOT_DUE",
}));

const hypothesisTitles: Record<string, string> = {
  "H11-001": "Buteur en forme contre deux centraux absents",
  "H11-002": "4-3-3 contre 4-4-2",
  "H11-003": "Pied fort et couloir défensif",
  "H11-004": "Gardien titulaire absent",
  "H11-005": "Nouveau duo central",
  "H11-006": "Continuité du onze",
  "H11-007": "Fatigue et changement tactique",
  "H11-008": "Confrontation structurelle",
};

const mechanisms: Record<string, string> = {
  "H11-001": "Une attaque en forme pourrait profiter d’une défense centrale remaniée.",
  "H11-002": "La structure du milieu pourrait créer un surnombre ou exposer les couloirs.",
  "H11-003": "L’orientation des appuis peut modifier la qualité des duels sur un côté.",
  "H11-004": "L’absence du gardien habituel peut modifier l’organisation défensive.",
  "H11-005": "Un duo central peu habitué à jouer ensemble peut manquer de coordination.",
  "H11-006": "La stabilité de l’équipe de départ peut améliorer les automatismes.",
  "H11-007": "Un calendrier dense peut favoriser une formation ou une rotation inhabituelle.",
  "H11-008": "Certaines structures tactiques peuvent se neutraliser ou créer un avantage local.",
};

export const hypotheses = snapshot.prospectiveObservatory.hypotheses.map((item) => ({
  id: item.id,
  title: hypothesisTitles[item.id] ?? "Hypothèse football",
  mechanism: mechanisms[item.id] ?? "Mécanisme à vérifier prospectivement.",
  requiredData: item.required_data,
  minimumSupport: item.minimum_support,
  observations: item.observations,
  coverage: item.coverage,
  status: item.status,
  frozen: item.frozen,
}));

export const gateRows = [
  { name: "Joueurs", technicalName: "PROSPECTIVE_PLAYER_GATE", status: "BLOCKED_BY_COVERAGE", passed: 0, total: 9, reason: "Aucune observation joueur prospective." },
  { name: "Blessures", technicalName: "PROSPECTIVE_INJURY_GATE", status: "BLOCKED_BY_COVERAGE", passed: 0, total: 9, reason: "Aucune indisponibilité sourcée avant l’heure limite." },
  { name: "Compositions", technicalName: "PROSPECTIVE_LINEUP_GATE", status: "BLOCKED_BY_COVERAGE", passed: 0, total: 9, reason: "Aucune composition officielle pré-match." },
  { name: "Formations", technicalName: "PROSPECTIVE_FORMATION_GATE", status: "BLOCKED_BY_COVERAGE", passed: 0, total: 9, reason: "La composition doit d’abord être vérifiée." },
  { name: "Marché", technicalName: "PROSPECTIVE_MARKET_GATE", status: "BLOCKED_BY_COVERAGE", passed: 0, total: 9, reason: "La couverture prospective des cotes est encore insuffisante." },
] as const;

export const dataFamilyLabels: Record<string, string> = {
  FIXTURE: "Rencontre",
  TEAM: "Équipe",
  SQUAD: "Effectif",
  PLAYER_STATUS: "État joueur",
  INJURY: "Blessures",
  LINEUP: "Composition",
  FORMATION: "Formation",
  ODDS: "Cotes",
  EVENT_STATUS: "État du match",
  FOOTEDNESS: "Pied fort",
};

export const oddsSnapshots = snapshot.odds.map((item) => ({
  id: item.snapshot_id,
  fixtureId: item.internal_fixture_id,
  observedAt: item.observed_at,
  provider: item.provider,
  bookmakers: item.bookmakers,
  quotes: item.quotes,
  markets: item.markets,
  hash: item.payload_hash,
}));

export const expertData = {
  datasets: snapshot.deepData.datasets,
  models: snapshot.deepData.models,
  backtests: snapshot.deepData.backtests,
  qualityChecks: snapshot.qualityChecks,
  providers: snapshot.providers,
  incidents: snapshot.incidents,
  quota: snapshot.quota,
  provenance: snapshot.provenance,
  externalValidation: snapshot.deepData.externalValidation,
  matchup: snapshot.matchupLab,
  patternResearch: snapshot.patternResearch,
};

export const scientificInvariants = snapshot.patternResearch;

const mojibakeReplacements: Array<[string, string]> = [
  ["â€™", "’"],
  ["â€“", "–"],
  ["â€”", "—"],
  ["â†’", "→"],
  ["â‰¥", "≥"],
  ["â‰¤", "≤"],
  ["Â·", "·"],
  ["Â", ""],
  ["Ã‰", "É"],
  ["Ã€", "À"],
  ["Ã‡", "Ç"],
  ["Ã©", "é"],
  ["Ã¨", "è"],
  ["Ãª", "ê"],
  ["Ã«", "ë"],
  ["Ã ", "à"],
  ["Ã¢", "â"],
  ["Ã§", "ç"],
  ["Ã®", "î"],
  ["Ã¯", "ï"],
  ["Ã´", "ô"],
  ["Ã¶", "ö"],
  ["Ã¹", "ù"],
  ["Ã»", "û"],
  ["Ã¼", "ü"],
  ["Å“", "œ"],
];

export function cleanFrench(value: unknown): string {
  return mojibakeReplacements.reduce(
    (text, [broken, fixed]) => text.replaceAll(broken, fixed),
    String(value ?? "—"),
  );
}
