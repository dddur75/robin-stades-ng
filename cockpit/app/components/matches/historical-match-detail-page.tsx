import Link from "next/link";

import { ExpertOnly } from "../common/view-mode";
import type {
  HistoricalHypothesisRelation,
  HistoricalRuleCondition,
} from "../../lib/historical-match-evidence";
import {
  historicalMatchDetailPath,
  historicalMatchListPath,
} from "../../lib/historical-match-evidence";
import type {
  HistoricalAdjacentMatch,
  HistoricalAdjacentHypothesis,
  HistoricalMatchDetailPageData,
} from "../../lib/historical-match-evidence.server";
import styles from "./historical-match-detail-page.module.css";

const dateFormatter = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "long",
  timeStyle: "short",
  timeZone: "Europe/Paris",
});
const shortDateFormatter = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeZone: "Europe/Paris",
});
const numberFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});
const signedFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  signDisplay: "always",
});
const percentFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  style: "percent",
});

const selectionLabels: Record<string, string> = {
  AWAY: "Victoire extérieure",
  DRAW: "Match nul",
  HOME: "Victoire domicile",
};
const outcomeLabels = {
  lost: "Perdu",
  void: "Annulé",
  won: "Gagné",
} as const;
const featureLabels: Record<string, string> = {
  competition: "Championnat",
  market_margin_1x2: "Marge du marché 1X2",
  odds_away: "Cote de la victoire extérieure",
  odds_draw: "Cote du match nul",
  odds_home: "Cote de la victoire à domicile",
};
const operatorLabels: Record<string, string> = {
  BETWEEN: "comprise entre",
  EQ: "égale à",
  GE: "supérieure ou égale à",
  GT: "supérieure à",
  IN: "comprise dans",
  LE: "inférieure ou égale à",
  LT: "inférieure à",
  NE: "différente de",
};
const reasonCodeLabels: Record<string, string> = {
  ALL_CONDITIONS_MATCH: "Toutes les conditions de la règle correspondent",
  OBSERVED_ODDS_ELIGIBLE: "La cote observée est éligible",
  OUTCOME_SETTLED: "Le résultat final est réglé",
};
const availabilityLabels: Record<string, string> = {
  FIXTURE_PUBLICATION: "à la publication de la rencontre",
  HISTORICAL_PRICE_CATEGORY: "dans la catégorie de prix historique",
};
const sourceLabels: Record<string, string> = {
  API_FOOTBALL_FIXTURE: "publication de la rencontre",
  FOOTBALL_DATA: "résultats et cotes historiques normalisés",
  SYNTHETIC_NORMALIZED_FIXTURE: "jeu de contrôle normalisé",
};
const observedTimeLabels: Record<string, string> = {
  SOURCE_PRICE_CLASS_ONLY:
    "Catégorie de prix historique ; heure exacte non prouvée",
};
const finalStatusLabels: Record<string, string> = {
  RESULT_RECORDED: "Résultat final enregistré",
};
const marketLabels: Record<string, string> = {
  "1X2_AWAY": "Résultat 1X2 · victoire extérieure",
  "1X2_DRAW": "Résultat 1X2 · match nul",
  "1X2_HOME": "Résultat 1X2 · victoire domicile",
};

function selectionLabel(value: string): string {
  return selectionLabels[value] ?? "Sélection historique documentée";
}

function SelectionValue({ value }: { value: string }) {
  return (
    <>
      {selectionLabel(value)}
      <ExpertOnly>
        {" "}
        <code>{value}</code>
      </ExpertOnly>
    </>
  );
}

function OperatorValue({ value }: { value: string }) {
  return (
    <>
      {operatorLabels[value] ?? "respecte le critère documenté"}
      <ExpertOnly>
        {" "}
        <code>{value}</code>
      </ExpertOnly>
    </>
  );
}

function formatUnits(value: number): string {
  return `${signedFormatter.format(value)} ${
    Math.abs(value) === 1 ? "unité" : "unités"
  }`;
}

function conditionFeature(value: string): string {
  return (
    featureLabels[value] ??
    value.replaceAll("_", " ").toLocaleLowerCase("fr-FR")
  );
}

function conditionValue(condition: HistoricalRuleCondition): string {
  const { value } = condition;
  const feature = condition.feature.toLocaleLowerCase("fr-FR");
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        typeof item === "number" ? numberFormatter.format(item) : String(item),
      )
      .join(" et ");
  }
  if (typeof value === "number") {
    return feature.includes("margin")
      ? percentFormatter.format(value)
      : numberFormatter.format(value);
  }
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "oui" : "non";
  if (value == null) return "valeur nulle documentée";
  return JSON.stringify(value);
}

function outcomeBadge(relation: HistoricalHypothesisRelation) {
  const outcome = relation.membership.outcome;
  return (
    <span className={`${styles.outcome} ${styles[outcome]}`}>
      {outcomeLabels[outcome]}
    </span>
  );
}

function profitClass(value: number): string {
  return value >= 0 ? styles.positive : styles.negative;
}

function AdjacentLink({
  activeHypothesisId,
  direction,
  match,
  returnTo,
}: {
  activeHypothesisId: string;
  direction: "next" | "previous";
  match: HistoricalAdjacentMatch | null;
  returnTo: string;
}) {
  const directionLabel =
    direction === "previous" ? "Match précédent" : "Match suivant";
  if (!match) {
    return (
      <span aria-disabled="true">
        <small>{directionLabel}</small>
        <strong>
          {direction === "previous"
            ? "Début de la série"
            : "Fin de la série"}
        </strong>
      </span>
    );
  }
  return (
    <Link
      aria-label={`${directionLabel} : ${match.label}`}
      href={historicalMatchDetailPath(match.canonicalMatchId, {
        hypothesisId: activeHypothesisId,
        returnTo,
      })}
      rel={direction === "previous" ? "prev" : "next"}
    >
      <small>{directionLabel}</small>
      <strong>{match.label}</strong>
      <small>
        {shortDateFormatter.format(new Date(match.kickoffAt))}
      </small>
    </Link>
  );
}

function AdjacentHypothesisLink({
  canonicalMatchId,
  direction,
  hypothesis,
}: {
  canonicalMatchId: string;
  direction: "next" | "previous";
  hypothesis: HistoricalAdjacentHypothesis | null;
}) {
  const directionLabel =
    direction === "previous"
      ? "Hypothèse précédente"
      : "Hypothèse suivante";
  if (!hypothesis) {
    return (
      <span aria-disabled="true">
        <small>{directionLabel}</small>
        <strong>
          {direction === "previous"
            ? "Début de l’aperçu"
            : "Fin de l’aperçu"}
        </strong>
      </span>
    );
  }
  const returnTo = historicalMatchListPath(hypothesis.hypothesisId);
  return (
    <Link
      aria-label={`${directionLabel} : ${hypothesis.hypothesisId}`}
      href={historicalMatchDetailPath(canonicalMatchId, {
        hypothesisId: hypothesis.hypothesisId,
        returnTo,
      })}
    >
      <small>{directionLabel}</small>
      <strong>{hypothesis.hypothesisId}</strong>
      <small>Même rencontre historique</small>
    </Link>
  );
}

function RelationCard({
  canonicalMatchId,
  relation,
}: {
  canonicalMatchId: string;
  relation: HistoricalHypothesisRelation;
}) {
  const listPath = historicalMatchListPath(relation.hypothesisId);
  return (
    <article className={styles.relationCard}>
      <header>
        <h3>{relation.hypothesisId}</h3>
        {outcomeBadge(relation)}
      </header>
      <p>
        <SelectionValue value={relation.membership.selection} />
        {" · cote "}
        {numberFormatter.format(relation.membership.observedOdds)}
        {" · profit "}
        <strong className={profitClass(relation.membership.profitUnits)}>
          {formatUnits(relation.membership.profitUnits)}
        </strong>
      </p>
      <div className={styles.relationActions}>
        <Link
          href={historicalMatchDetailPath(canonicalMatchId, {
            hypothesisId: relation.hypothesisId,
            returnTo: listPath,
          })}
        >
          Voir pourquoi
        </Link>
        <Link href={`/hypotheses/${relation.hypothesisId}`}>
          Ouvrir l’hypothèse
        </Link>
      </div>
    </article>
  );
}

export function HistoricalMatchDetailPage({
  data,
}: {
  data: HistoricalMatchDetailPageData;
}) {
  const { activeRelation, detail, navigation } = data;
  const fixture = detail.fixture;
  const finalScore =
    `${fixture.finalScore.home} – ${fixture.finalScore.away}`;
  const matchTitle =
    `${fixture.homeTeam.name} – ${fixture.awayTeam.name}`;

  return (
    <div className={styles.page}>
      <nav aria-label="Fil d’Ariane" className={styles.breadcrumbs}>
        <ol>
          <li>
            <Link href="/robin-live">Accueil</Link>
          </li>
          <li>
            <Link href="/matchs">Matchs</Link>
          </li>
          <li>
            <Link href={data.returnTo}>{activeRelation.hypothesisId}</Link>
          </li>
          <li>
            <span aria-current="page">{matchTitle}</span>
          </li>
        </ol>
      </nav>

      {data.contextRequestedButUnavailable ? (
        <p className={styles.contextWarning} role="alert">
          L’hypothèse demandée ne contient pas ce match dans l’artefact
          réconcilié. Robin a basculé vers la première relation historique
          vérifiée, sans inventer de lien.
        </p>
      ) : null}

      <header className={styles.hero}>
        <div className={styles.heroTop}>
          <div>
            <span className={`${styles.badge} ${styles.historicalBadge}`}>
              Simulation historique
            </span>
            <span className={styles.badge}>{fixture.competition}</span>
            <span className={styles.badge}>Saison {fixture.season}</span>
            <span className={styles.badge}>
              {finalStatusLabels[fixture.finalStatus] ??
                "Résultat final documenté"}
            </span>
          </div>
          <ExpertOnly>
            <code>{detail.canonicalMatchId}</code>
          </ExpertOnly>
        </div>
        <div className={styles.matchHeading}>
          <p>Rencontre historique réconciliée</p>
          <h1>{matchTitle}</h1>
        </div>
        <div className={styles.scoreboard}>
          <section className={styles.team}>
            <span aria-hidden="true">D</span>
            <h2>{fixture.homeTeam.name}</h2>
            <p>
              Domicile
              <ExpertOnly> · ID {fixture.homeTeam.id}</ExpertOnly>
            </p>
          </section>
          <div className={styles.score}>
            <strong aria-label={`Score final ${finalScore}`}>
              {finalScore}
            </strong>
            <p>
              <time dateTime={fixture.kickoffAt}>
                {dateFormatter.format(new Date(fixture.kickoffAt))}
              </time>
            </p>
          </div>
          <section className={styles.team}>
            <span aria-hidden="true">E</span>
            <h2>{fixture.awayTeam.name}</h2>
            <p>
              Extérieur
              <ExpertOnly> · ID {fixture.awayTeam.id}</ExpertOnly>
            </p>
          </section>
        </div>
        <div className={styles.contextBar}>
          <p>
            <strong>
              {detail.totalHistoricalRules} règle
              {detail.totalHistoricalRules > 1 ? "s" : ""} historique
              {detail.totalHistoricalRules > 1 ? "s" : ""} réconciliée
              {detail.totalHistoricalRules > 1 ? "s" : ""}
            </strong>
            {" ; aperçu borné de "}
            <strong>
              {detail.relations.length} relation
              {detail.relations.length > 1 ? "s" : ""} navigable
              {detail.relations.length > 1 ? "s" : ""}
            </strong>
            . Contexte actif : <strong>{activeRelation.hypothesisId}</strong>
          </p>
          <Link href={`/hypotheses/${activeRelation.hypothesisId}`}>
            Ouvrir la fiche hypothèse
          </Link>
        </div>
      </header>

      <nav
        aria-label="Navigation entre les hypothèses réconciliées de ce match"
        className={`${styles.navigation} ${styles.hypothesisNavigation}`}
      >
        <AdjacentHypothesisLink
          canonicalMatchId={detail.canonicalMatchId}
          direction="previous"
          hypothesis={navigation.previousHypothesis}
        />
        <span className={styles.navigationPosition}>
          <small>Hypothèse active</small>
          <strong>{activeRelation.hypothesisId}</strong>
        </span>
        <AdjacentHypothesisLink
          canonicalMatchId={detail.canonicalMatchId}
          direction="next"
          hypothesis={navigation.nextHypothesis}
        />
      </nav>

      <nav
        aria-label={`Navigation chronologique dans ${activeRelation.hypothesisId}`}
        className={styles.navigation}
      >
        <AdjacentLink
          activeHypothesisId={activeRelation.hypothesisId}
          direction="previous"
          match={navigation.previous}
          returnTo={data.returnTo}
        />
        <Link className={styles.backLink} href={data.returnTo}>
          ← Retour à la liste contextuelle
        </Link>
        <AdjacentLink
          activeHypothesisId={activeRelation.hypothesisId}
          direction="next"
          match={navigation.next}
          returnTo={data.returnTo}
        />
      </nav>

      <div className={styles.grid}>
        <section className={styles.panel}>
          <p className={styles.panelEyebrow}>Appartenance vérifiée</p>
          <h2>Pourquoi ce match appartenait à cette hypothèse</h2>
          <p className={styles.panelIntro}>
            La règle {activeRelation.hypothesisId} comportait les conditions
            suivantes. L’artefact atteste l’appartenance globale et le
            règlement du résultat.
          </p>

          <dl className={styles.metrics}>
            <div>
              <dt>Sélection</dt>
              <dd>
                <SelectionValue
                  value={activeRelation.membership.selection}
                />
              </dd>
            </div>
            <div>
              <dt>Cote observée</dt>
              <dd>
                {numberFormatter.format(
                  activeRelation.membership.observedOdds,
                )}
              </dd>
            </div>
            <div>
              <dt>Marge du marché</dt>
              <dd>
                {percentFormatter.format(
                  activeRelation.membership.marketMargin,
                )}
              </dd>
            </div>
            <div>
              <dt>Résultat</dt>
              <dd>{outcomeBadge(activeRelation)}</dd>
            </div>
            <div>
              <dt>Profit simulé</dt>
              <dd
                className={profitClass(
                  activeRelation.membership.profitUnits,
                )}
              >
                {signedFormatter.format(
                  activeRelation.membership.profitUnits,
                )}
                {Math.abs(activeRelation.membership.profitUnits) === 1
                  ? " unité"
                  : " unités"}
              </dd>
            </div>
            <div>
              <dt>Marché</dt>
              <dd>
                {marketLabels[activeRelation.membership.market] ??
                  "Marché historique documenté"}
                <ExpertOnly>
                  {" "}
                  <code>{activeRelation.membership.market}</code>
                </ExpertOnly>
              </dd>
            </div>
          </dl>

          <ol className={styles.conditions}>
            {data.conditions.map((condition, index) => (
              <li key={`${condition.feature}-${condition.operator}-${index}`}>
                <div>
                  <strong>
                    {conditionFeature(condition.feature)}{" "}
                    <OperatorValue value={condition.operator} />{" "}
                    {conditionValue(condition)}
                  </strong>
                  <p>
                    {condition.source
                      ? `Source : ${sourceLabels[condition.source] ?? "source historique documentée"}`
                      : "Source portée par le contrat de règle"}
                    {condition.availableAt
                      ? ` · ${availabilityLabels[condition.availableAt] ?? "disponibilité documentée"}`
                      : ""}
                    <ExpertOnly>
                      {condition.source ? (
                        <>
                          {" "}
                          · <code>{condition.source}</code>
                        </>
                      ) : null}
                      {condition.availableAt ? (
                        <>
                          {" "}
                          · <code>{condition.availableAt}</code>
                        </>
                      ) : null}
                    </ExpertOnly>
                  </p>
                </div>
                <span>Condition documentée</span>
              </li>
            ))}
          </ol>

          <p className={styles.reasonNote}>
            L’artefact source ne stocke pas de booléen par condition. Robin ne
            prétend donc pas reconstituer ici une évaluation unitaire : il
            affiche les conditions de la règle et les codes d’éligibilité
            globaux, exactement séparés.
          </p>
          <div
            aria-label="Codes d’éligibilité historiques"
            className={styles.reasonCodes}
          >
            {activeRelation.reason.codes.map((code) => (
              <span key={code}>
                {reasonCodeLabels[code] ?? "Éligibilité historique documentée"}
                <ExpertOnly>
                  {" "}
                  <code>{code}</code>
                </ExpertOnly>
              </span>
            ))}
          </div>
        </section>

        <aside className={styles.panel}>
          <p className={styles.panelEyebrow}>Même rencontre</p>
          <h2>Autres hypothèses</h2>
          <p className={styles.panelIntro}>
            Aperçu borné des relations navigables contenant exactement ce
            match.
          </p>
          {data.otherRelations.length === 0 ? (
            <p className={styles.emptyRelations}>
              Aucune autre relation navigable ne contient cette rencontre.
            </p>
          ) : (
            <div className={styles.otherList}>
              {data.otherRelations.map((relation) => (
                <RelationCard
                  canonicalMatchId={detail.canonicalMatchId}
                  key={relation.hypothesisId}
                  relation={relation}
                />
              ))}
            </div>
          )}
        </aside>
      </div>

      <section className={styles.panel}>
        <p className={styles.panelEyebrow}>Traçabilité</p>
        <h2>Source et provenance</h2>
        <dl className={styles.sourceList}>
          <div>
            <dt>Source normalisée</dt>
            <dd>
              {sourceLabels[detail.source.source] ??
                "Source historique normalisée"}
              <ExpertOnly>
                {" "}
                <code>{detail.source.source}</code>
              </ExpertOnly>
            </dd>
          </div>
          <div>
            <dt>Date du match</dt>
            <dd>{fixture.matchDate}</dd>
          </div>
          <div>
            <dt>Statut temporel de la cote</dt>
            <dd>
              {observedTimeLabels[detail.source.observedTimeStatus] ??
                "Disponibilité temporelle documentée"}
              <ExpertOnly>
                {" "}
                <code>{detail.source.observedTimeStatus}</code>
              </ExpertOnly>
            </dd>
          </div>
          <ExpertOnly>
            <div>
              <dt>Hash du jeu de données</dt>
              <dd>
                <code>{detail.source.datasetHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash de la ligne source</dt>
              <dd>
                <code>{detail.source.sourceRowHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash d’appartenance</dt>
              <dd>
                <code>{activeRelation.membership.membershipHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash de règle</dt>
              <dd>
                <code>{activeRelation.ruleHash}</code>
              </dd>
            </div>
          </ExpertOnly>
        </dl>
        <p className={styles.sourceWarning}>
          Le statut temporel documente une catégorie de prix historique ; il
          ne prouve pas une heure intrajournalière exacte. Aucune observation
          prospective n’est incluse dans cette fiche.
        </p>
      </section>
    </div>
  );
}
