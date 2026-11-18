export type PilotVersion = {
  observedAt: string;
  detectedAt: string;
  publishedAt: string | null;
  market: string;
  selection: string;
  period: string | null;
  line: string | null;
  odds: string | null;
  sourceUrl: string;
};

export type PilotPick = {
  id: string;
  providerId: string;
  fixtureId: string;
  authorId: string;
  attributionBasis: "declared" | "publication";
  firstSeenAt: string;
  lastSeenAt: string;
  versions: PilotVersion[];
};

export type PilotSnapshot = {
  status: "ok";
  schemaVersion: "robin-tipsters-pilot-v1";
  generatedAt: string;
  phase: "scheduled" | "collecting" | "closed";
  source: string;
  missionId: string;
  startsAt: string;
  expiresAt: string;
  requestsMax: number;
  plannedSlots: number;
  plannedVisits: number;
  journalPresent: boolean;
  journalHead: string | null;
  counts: Record<string, number>;
  distinctPicks: number | null;
  lastObservationAt: string | null;
  technicalVerdict: "PENDING" | "PARTIAL" | "PASS_AND_HOLD";
  dossierVerdict: "PARTIAL";
  fixtures: { id: string; label: string; kickoff: string }[];
  visits: { slot: string; fixtureId: string; status: string; observedAt: string | null; picks: number | null }[];
  tipsters: {
    id: string;
    label: string;
    attributionBasis: "declared" | "publication";
    picks: number;
    fixtureIds: string[];
    firstSeenAt: string;
    lastSeenAt: string;
  }[];
  picks: PilotPick[];
  evidence: { claimId: string; planSha256: string; journalHeadSha256: string | null; method: string };
};

export const visitLabels: Record<string, string> = {
  planned: "À venir", running: "En cours", interrupted: "Interrompue", missed: "Créneau manqué",
  succeeded: "Réussie", failed: "Échec de lecture", blocked: "Bloquée par robots.txt", skipped: "Arrêt de sécurité",
};

export const marketLabels: Record<string, string> = {
  "1x2": "Résultat du match", match_result: "Résultat du match", total: "Total de buts",
  totals: "Total de buts", handicap: "Handicap", both_teams_to_score: "Les deux équipes marquent",
};

export const selectionLabels: Record<string, string> = {
  home: "Domicile", away: "Extérieur", draw: "Match nul", over: "Plus de", under: "Moins de", yes: "Oui", no: "Non",
};

export const periodLabels: Record<string, string> = {
  full_time: "Temps réglementaire", first_half: "Première mi-temps", second_half: "Seconde mi-temps",
};
