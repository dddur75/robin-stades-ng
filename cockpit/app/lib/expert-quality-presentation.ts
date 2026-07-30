export const HISTORICAL_DATA_LABEL = "DONNÉE HISTORIQUE";
export const SNAPSHOT_UNVERIFIABLE_LABEL = "Non vérifiable dans ce snapshot";

type LegacyQualityCheck = Readonly<{
  check: string;
  origin: string;
  status: string;
  threshold: string;
  value: string;
}>;

type LegacyProvenance = Readonly<{
  sourceCommit: string;
  stateArtifact: string;
}>;

export type HistoricalQualityRow = {
  check: string;
  origin: string;
  provenance: string;
  status: string;
  threshold: string;
  value: string;
};

export function buildHistoricalQualityRows(
  checks: readonly LegacyQualityCheck[],
  provenance: LegacyProvenance,
): HistoricalQualityRow[] {
  return checks.map((row) => ({
    ...row,
    provenance: [
      HISTORICAL_DATA_LABEL,
      provenance.stateArtifact,
      provenance.sourceCommit,
    ].join(" · "),
  }));
}

type CurrentOperationalEvidence = Readonly<{
  generatedAt: string;
  sourceRevision: string;
  sourceRun: string;
  freshness: Readonly<{
    ageMinutes: number | null;
    status: string;
  }>;
  postgresql: Readonly<{
    inserts: number;
    lag: number;
    migration: string;
    reconstructionStatus: string;
    tables: number;
  }>;
  providers: Readonly<{
    apiFootballCalls: number;
    apiFootballCap: number;
    oddsApiCredits: number;
    oddsApiCap: number;
  }>;
  r2: Readonly<{
    lag: number;
    objects: number;
    replayStatus: string;
    verified: number;
  }>;
}>;

export type CurrentQualityRow = {
  control: string;
  evidence: string;
  limits: string;
  source: string;
  status: string;
};

export function buildCurrentQualityRows(
  evidence: CurrentOperationalEvidence,
): CurrentQualityRow[] {
  const source = `Run ${evidence.sourceRun} · révision ${evidence.sourceRevision}`;
  return [
    {
      control: "PostgreSQL",
      evidence: `${evidence.postgresql.migration} · ${evidence.postgresql.tables} tables · ${evidence.postgresql.inserts} insertions · lag ${evidence.postgresql.lag}`,
      limits: "État reconstruit depuis la preuve opérationnelle horodatée.",
      source,
      status: evidence.postgresql.reconstructionStatus,
    },
    {
      control: "R2",
      evidence: `${evidence.r2.verified} / ${evidence.r2.objects} objets vérifiés · lag ${evidence.r2.lag}`,
      limits: "Aucune écriture ni suppression déclenchée par cette consultation.",
      source,
      status: evidence.r2.replayStatus,
    },
    {
      control: "API-Football",
      evidence: `${evidence.providers.apiFootballCalls} appels enregistrés · plafond ${evidence.providers.apiFootballCap}`,
      limits: `Plan, présence de clé et dernier appel exact : ${SNAPSHOT_UNVERIFIABLE_LABEL.toLowerCase()}. Aucune valeur de secret n’est exposée.`,
      source,
      status: evidence.providers.apiFootballCalls > 0
        ? "CAPTURES_RECORDED"
        : "NO_CAPTURE_RECORDED",
    },
    {
      control: "The Odds API",
      evidence: `${evidence.providers.oddsApiCredits} crédits enregistrés · plafond ${evidence.providers.oddsApiCap}`,
      limits: `Authentification, réserve et dernière capture exacte : ${SNAPSHOT_UNVERIFIABLE_LABEL.toLowerCase()}.`,
      source,
      status: evidence.providers.oddsApiCredits > 0
        ? "CAPTURES_RECORDED"
        : "NO_CAPTURE_RECORDED",
    },
    {
      control: "football-data.org",
      evidence: "Compte et plan distincts de Football-Data.co.uk.",
      limits: `Compte, plan et usage courant : ${SNAPSHOT_UNVERIFIABLE_LABEL.toLowerCase()}.`,
      source: "Aucune source opérationnelle courante dans cet artefact.",
      status: "NO_CURRENT_OPERATIONAL_EVIDENCE",
    },
    {
      control: "Football-Data.co.uk",
      evidence: "Source de résultats et de cotes historiques normalisés.",
      limits: "Ne constitue ni un compte football-data.org ni une preuve fournisseur courante.",
      source: "Référentiel historique distinct ; voir les contrôles legacy.",
      status: "HISTORICAL_SOURCE_ONLY",
    },
  ];
}
