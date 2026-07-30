import { formatNumber } from "../../i18n";
import {
  formatEvidenceNumber,
  formatEvidencePercent,
  formatEvidenceUnits,
} from "../../lib/hypothesis-evidence-format";
import type {
  HistoricalEvidenceCondition,
  HistoricalHypothesisEvidence,
} from "../../lib/hypothesis-evidence.server";
import {
  HypothesisBankrollChart,
  type HypothesisBankrollPoint,
} from "./hypothesis-bankroll-chart";
import {
  HypothesisFoldValidation,
  type HypothesisFoldEvidence,
} from "./hypothesis-fold-validation";
import {
  HypothesisOddsDistribution,
  type HypothesisOddsBin,
} from "./hypothesis-odds-distribution";
import { UniverseSectionHeading } from "./hypothesis-primitives";
import {
  HypothesisSeasonBreakdown,
  type HypothesisSeasonEvidence,
} from "./hypothesis-season-breakdown";
import {
  HypothesisStreakBreakdown,
  type HypothesisStreakRun,
  type HypothesisStreakSummary,
} from "./hypothesis-streak-breakdown";
import {
  HypothesisTeamConcentration,
  type HypothesisTeamConcentrationItem,
} from "./hypothesis-team-concentration";

export type HistoricalEvidenceVisualData = Readonly<{
  bankroll: readonly HypothesisBankrollPoint[];
  folds: readonly HypothesisFoldEvidence[];
  odds: readonly HypothesisOddsBin[];
  seasons: readonly HypothesisSeasonEvidence[];
  streaks: Readonly<{
    losing: HypothesisStreakSummary;
    runs: readonly HypothesisStreakRun[];
    winning: HypothesisStreakSummary;
  }>;
  teams: readonly HypothesisTeamConcentrationItem[];
  teamTotalMatches: number;
}>;

export const EMPTY_HISTORICAL_EVIDENCE_VISUAL_DATA: HistoricalEvidenceVisualData =
  Object.freeze({
    bankroll: Object.freeze([]),
    folds: Object.freeze([]),
    odds: Object.freeze([]),
    seasons: Object.freeze([]),
    streaks: Object.freeze({
      losing: Object.freeze({
        currentLength: 0,
        longestLength: 0,
        runCount: 0,
      }),
      runs: Object.freeze([]),
      winning: Object.freeze({
        currentLength: 0,
        longestLength: 0,
        runCount: 0,
      }),
    }),
    teams: Object.freeze([]),
    teamTotalMatches: 0,
  });

function conditionFeatureLabel(feature: string) {
  const labels: Record<string, string> = {
    competition: "Championnat",
    market_margin_1x2: "Marge du marché",
    odds_away: "Cote de la victoire extérieure",
    odds_draw: "Cote du match nul",
    odds_home: "Cote de la victoire à domicile",
  };
  return labels[feature] ?? "Condition documentée";
}

function conditionValue(
  condition: HistoricalEvidenceCondition,
): string {
  const { feature, operator, value } = condition;
  if (
    operator === "BETWEEN" &&
    Array.isArray(value) &&
    typeof value[0] === "number" &&
    typeof value[1] === "number"
  ) {
    return `entre ${formatEvidenceNumber(value[0])} et ${formatEvidenceNumber(
      value[1],
    )}`;
  }
  if (
    operator === "LE" &&
    typeof value === "number" &&
    feature.includes("margin")
  ) {
    return `inférieure ou égale à ${formatEvidencePercent(value)}`;
  }
  if (operator === "LE" && typeof value === "number") {
    return `inférieure ou égale à ${formatEvidenceNumber(value)}`;
  }
  if (operator === "GE" && typeof value === "number") {
    return `supérieure ou égale à ${formatEvidenceNumber(value)}`;
  }
  if (
    operator === "EQ" &&
    (typeof value === "string" || typeof value === "number")
  ) {
    return String(value);
  }
  return "Valeur disponible en Vue Expert";
}

export function HistoricalEvidenceConditionsAndCoverage({
  evidence,
}: {
  evidence: HistoricalHypothesisEvidence;
}) {
  const coverage = evidence.statisticalCoverage;
  return (
    <section className="hu-section hu-surface">
      <UniverseSectionHeading
        eyebrow="Règle et couverture"
        subtitle="Les conditions viennent du rapport réconcilié ; les nombres de groupes ne sont pas une ventilation détaillée."
        title="Conditions historiques observées"
      />
      <div className="hu-condition-grid">
        {evidence.conditions.map((condition, index) => (
          <article key={`${condition.feature}-${index}`}>
            <span aria-hidden="true">◇</span>
            <div>
              <strong>{conditionFeatureLabel(condition.feature)}</strong>
              <p>{conditionValue(condition)}</p>
              <small>
                Disponibilité :{" "}
                {condition.availableAt === "FIXTURE_PUBLICATION"
                  ? "publication de la rencontre"
                  : "classe de prix historique"}
              </small>
            </div>
          </article>
        ))}
      </div>
      <dl className="hu-detail-list hu-statistical-coverage">
        <div>
          <dt>Groupes statistiques distincts</dt>
          <dd>{formatNumber(coverage.statisticalGroups)}</dd>
        </div>
        <div>
          <dt>Saisons distinctes</dt>
          <dd>{formatNumber(coverage.distinctSeasons)}</dd>
        </div>
        <div>
          <dt>Équipes distinctes</dt>
          <dd>{formatNumber(coverage.distinctTeams)}</dd>
        </div>
        <div>
          <dt>Capital total simulé</dt>
          <dd>{formatEvidenceUnits(coverage.totalStakedUnits)}</dd>
        </div>
        <div>
          <dt>Retours bruts simulés</dt>
          <dd>{formatEvidenceUnits(coverage.grossReturnsUnits)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function HistoricalEvidenceVisuals({
  visuals = EMPTY_HISTORICAL_EVIDENCE_VISUAL_DATA,
}: {
  visuals?: HistoricalEvidenceVisualData;
}) {
  const sourceNote =
    "Les ventilations sont chargées séparément de la fiche agrégée ; une collection vide reste affichée comme indisponible.";
  return (
    <section
      aria-labelledby="historical-visuals-title"
      className="hu-section"
    >
      <UniverseSectionHeading
        eyebrow="Détails bornés"
        subtitle="Chaque graphique reçoit sa propre collection. Aucune série n’est reconstruite depuis un total."
        title="Décomposer la preuve historique"
      />
      <span className="sr-only" id="historical-visuals-title">
        Décomposer la preuve historique
      </span>
      <div className="hu-evidence-visual-grid">
        <HypothesisBankrollChart
          points={visuals.bankroll}
          sourceNote={sourceNote}
        />
        <HypothesisFoldValidation
          folds={visuals.folds}
          interpretation="chronological-periods"
          sourceNote={sourceNote}
        />
        <HypothesisOddsDistribution
          bins={visuals.odds}
          sourceNote={sourceNote}
        />
        <HypothesisSeasonBreakdown
          seasons={visuals.seasons}
          sourceNote={sourceNote}
        />
        <HypothesisTeamConcentration
          items={visuals.teams}
          sourceNote={sourceNote}
          totalMatches={visuals.teamTotalMatches}
        />
        <HypothesisStreakBreakdown
          losing={visuals.streaks.losing}
          runs={visuals.streaks.runs}
          sourceNote={sourceNote}
          winning={visuals.streaks.winning}
        />
      </div>
    </section>
  );
}
