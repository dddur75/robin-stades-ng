"use client";

import Link from "next/link";
import {
  useState,
  type ReactNode,
} from "react";

import {
  formatDateTime,
  formatNumber,
} from "../../i18n";
import {
  formatEvidenceNumber,
  formatEvidencePercent,
  formatEvidenceUnits,
} from "../../lib/hypothesis-evidence-format";
import type { HistoricalHypothesisEvidence } from "../../lib/hypothesis-evidence.server";
import { AccessibleTabs } from "../common/accessible-tabs";
import { useViewMode } from "../common/view-mode";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  MetricExplainer,
  ScientificStatusBadge,
  TagChip,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

function selectionLabel(selection: string) {
  const labels: Record<string, string> = {
    AWAY: "Victoire à l’extérieur",
    DRAW: "Match nul",
    HOME: "Victoire à domicile",
  };
  return labels[selection] ?? "Sélection documentée";
}

function marketLabel(market: string) {
  const labels: Record<string, string> = {
    "1X2_AWAY": "Résultat du match · victoire à l’extérieur",
    "1X2_DRAW": "Résultat du match · match nul",
    "1X2_HOME": "Résultat du match · victoire à domicile",
  };
  return labels[market] ?? "Marché documenté";
}

function percentagePosition(value: number) {
  return Math.max(0, Math.min(100, ((value + 0.1) / 0.5) * 100));
}

type EvidencePhase = "historical" | "prospective";

export function HistoricalEvidenceDetail({
  conditionsAndCoverage,
  evidence,
  visualizations,
}: {
  conditionsAndCoverage: ReactNode;
  evidence: HistoricalHypothesisEvidence;
  visualizations: ReactNode;
}) {
  const { mode } = useViewMode();
  const [phaseTab, setPhaseTab] = useState<
    "historical" | "prospective"
  >("historical");
  const metrics = evidence.metrics;
  const intervalStart = percentagePosition(metrics.confidenceInterval[0]);
  const intervalEnd = percentagePosition(metrics.confidenceInterval[1]);
  const exactTimeAvailable =
    evidence.temporalEvidence.exactIntradayTimestamp &&
    evidence.temporalEvidence.pointInTimeClaim;

  return (
    <>
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { href: "/hypotheses/classements", label: "Classements" },
          { label: evidence.hypothesisId },
        ]}
      />
      <HypothesisSubnav />

      <header className="hu-detail-hero">
        <div>
          <div className="hu-tag-list">
            <TagChip kind="family">{evidence.competition}</TagChip>
            <TagChip kind="value">
              {selectionLabel(evidence.selection)}
            </TagChip>
            <TagChip kind="science">
              Découverte historique de Robin
            </TagChip>
            <ScientificStatusBadge status={evidence.scientificStatus} />
          </div>
          <p className="hu-kicker">
            Hypothèse {evidence.hypothesisId}
          </p>
          <h1>{evidence.labelFr}</h1>
          <p>
            Observer historiquement {selectionLabel(evidence.selection).toLocaleLowerCase("fr-FR")}{" "}
            en {evidence.competition}, sur le marché{" "}
            {marketLabel(evidence.market).toLocaleLowerCase("fr-FR")}. Les{" "}
            {formatNumber(evidence.conditions.length)} conditions exactes sont
            publiées ci-dessous ; la source ne revendique pas d’heure
            intrajournalière exacte.
          </p>
        </div>
        <aside>
          <span aria-hidden="true">R</span>
          <strong>Découverte automatiquement par Robin</strong>
          <p>
            {evidence.rankByRoi == null
              ? "Cette règle apparaît dans une portée bornée du rapport historique."
              : `Cette règle occupe le rang ${evidence.rankByRoi} du classement global par résultat historique brut.`}
          </p>
        </aside>
      </header>

      <section
        aria-label="Carte de preuve historique"
        className="hu-section hu-surface hu-mode-summary"
        data-view-mode={mode}
      >
        <UniverseSectionHeading
          action={
            <Link
              className="hu-text-link"
              href={`/hypotheses/${encodeURIComponent(evidence.hypothesisId)}/matchs`}
            >
              Voir les {formatNumber(metrics.occurrences)} matchs historiques
            </Link>
          }
          eyebrow="Preuve historique réconciliée"
          subtitle={
            mode === "discovery"
              ? "Ces valeurs décrivent une simulation passée. Elles ne constituent ni une validation scientifique ni une promesse future."
              : "Les principales valeurs restent visibles dans tous les modes ; les ventilations et la provenance suivent plus bas."
          }
          title="L’essentiel, chiffres compris"
        />
        <div className="hu-key-metrics hu-detail-metrics">
          <UniverseMetric
            detail="observations strictement éligibles"
            label="Occurrences historiques"
            tone="blue"
            value={metrics.occurrences}
          />
          <UniverseMetric
            detail="résultats historiques réglés"
            label="Gagnés"
            tone="teal"
            value={metrics.wins}
          />
          <UniverseMetric
            detail="résultats historiques réglés"
            label="Perdus"
            tone="coral"
            value={metrics.losses}
          />
          <UniverseMetric
            detail="gagnés parmi les résultats réglés"
            label="Taux de réussite"
            tone="violet"
            value={formatEvidencePercent(metrics.hitRate)}
          />
          <UniverseMetric
            detail="calculée sur les matchs reconstruits"
            label="Cote moyenne"
            value={formatEvidenceNumber(metrics.averageOdds)}
          />
          <UniverseMetric
            detail="capital de simulation"
            label="Profit simulé"
            tone="teal"
            value={formatEvidenceUnits(metrics.profitUnits, true)}
          />
          <UniverseMetric
            detail="simulation historique"
            label="ROI historique brut"
            tone="gold"
            value={formatEvidencePercent(metrics.roi, true)}
          />
          <UniverseMetric
            detail="repli depuis un sommet de la simulation"
            label="Baisse maximale"
            tone="coral"
            value={formatEvidenceUnits(metrics.maximumDrawdownUnits)}
          />
          <UniverseMetric
            detail="validation chronologique glissante"
            label="Périodes positives"
            tone="blue"
            value={`${metrics.positiveFolds}/${metrics.eligibleFolds}`}
          />
          <UniverseMetric
            detail="non validé après correction statistique"
            label="Statut scientifique"
            tone="violet"
            value="Exploratoire"
          />
        </div>
      </section>

      <AccessibleTabs<EvidencePhase>
        ariaLabel="Phases de preuve de l’hypothèse"
        idBase={`evidence-phase-${evidence.hypothesisId}`}
        onChange={setPhaseTab}
        tabs={[
          {
            id: "historical",
            label: "Simulation historique",
            panel: (
              <div className="hu-evidence-phase-panel">
                <article className="hu-section hu-surface">
                  <UniverseSectionHeading
                    eyebrow="Simulation historique"
                    title="Ce que le passé montre"
                  />
                  <div className="hu-confidence-chart">
                    <div
                      aria-label={`Intervalle historique de ${formatEvidencePercent(
                        metrics.confidenceInterval[0],
                        true,
                      )} à ${formatEvidencePercent(
                        metrics.confidenceInterval[1],
                        true,
                      )}`}
                      role="img"
                    >
                      <span
                        style={{
                          left: `${intervalStart}%`,
                          right: `${100 - intervalEnd}%`,
                        }}
                      />
                      <i
                        style={{
                          left: `${percentagePosition(metrics.roi)}%`,
                        }}
                      />
                    </div>
                    <p>
                      Intervalle observé :{" "}
                      {formatEvidencePercent(
                        metrics.confidenceInterval[0],
                        true,
                      )}{" "}
                      à{" "}
                      {formatEvidencePercent(
                        metrics.confidenceInterval[1],
                        true,
                      )}
                      .
                    </p>
                  </div>
                  <dl className="hu-detail-list">
                    <div>
                      <dt>Occurrences historiques</dt>
                      <dd>{formatNumber(metrics.occurrences)}</dd>
                    </div>
                    <div>
                      <dt>ROI historique brut</dt>
                      <dd>{formatEvidencePercent(metrics.roi, true)}</dd>
                    </div>
                    <div>
                      <dt>Profit simulé</dt>
                      <dd>{formatEvidenceUnits(metrics.profitUnits, true)}</dd>
                    </div>
                    <div>
                      <dt>Gagnés / perdus / annulés</dt>
                      <dd>
                        {formatNumber(metrics.wins)} /{" "}
                        {formatNumber(metrics.losses)} /{" "}
                        {formatNumber(metrics.voids)}
                      </dd>
                    </div>
                    <div>
                      <dt>Taux de réussite</dt>
                      <dd>{formatEvidencePercent(metrics.hitRate)}</dd>
                    </div>
                    <div>
                      <dt>Cote moyenne</dt>
                      <dd>{formatEvidenceNumber(metrics.averageOdds)}</dd>
                    </div>
                    <div>
                      <dt>Baisse maximale</dt>
                      <dd>
                        {formatEvidenceUnits(
                          metrics.maximumDrawdownUnits,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Validation chronologique glissante</dt>
                      <dd>
                        {metrics.positiveFolds}/{metrics.eligibleFolds} périodes
                        positives
                      </dd>
                    </div>
                    <div>
                      <dt>Risque de faux positif après correction</dt>
                      <dd>
                        {mode === "discovery"
                          ? "Ne passe pas le contrôle"
                          : formatEvidenceNumber(
                              metrics.correctedFalsePositiveRisk,
                            )}
                      </dd>
                    </div>
                    <div>
                      <dt>Statut scientifique</dt>
                      <dd>
                        <ScientificStatusBadge
                          status={evidence.scientificStatus}
                        />
                      </dd>
                    </div>
                    {mode === "discovery" ? null : (
                      <>
                        <div>
                          <dt>Cote médiane</dt>
                          <dd>{formatEvidenceNumber(metrics.medianOdds)}</dd>
                        </div>
                        <div>
                          <dt>Plus longue série de pertes</dt>
                          <dd>
                            {formatNumber(metrics.longestLosingStreak)} matchs
                          </dd>
                        </div>
                      </>
                    )}
                  </dl>
                  <p className="hu-evidence-warning">{evidence.warningFr}</p>
                </article>
                {conditionsAndCoverage}
                {mode === "discovery" ? null : visualizations}
              </div>
            ),
          },
          {
            id: "prospective",
            label: "Observation depuis le gel",
            panel: (
              <article className="hu-section hu-surface">
                <UniverseSectionHeading
                  eyebrow="Séparation des phases"
                  title="Observation depuis le gel"
                />
                <HonestEmptyState title="Aucune preuve prospective dans ce rapport">
                  Cette fiche lit exclusivement la preuve historique Jalon 10.
                  Elle ne transforme jamais les{" "}
                  {formatNumber(metrics.settledOccurrences)} résultats
                  historiques réglés en observations futures.
                </HonestEmptyState>
                <dl className="hu-detail-list">
                  <div>
                    <dt>Heure intrajournalière exacte</dt>
                    <dd>{exactTimeAvailable ? "Prouvée" : "Non prouvée"}</dd>
                  </div>
                  <div>
                    <dt>Contrat temporel source</dt>
                    <dd>Classe de prix source uniquement</dd>
                  </div>
                </dl>
              </article>
            ),
          },
        ]}
        value={phaseTab}
      />

      <section className="hu-not-validated">
        <span aria-hidden="true">!</span>
        <div>
          <p className="hu-kicker">Limite essentielle</p>
          <h2>Pourquoi ce signal n’est pas validé</h2>
          <p>
            Son statut public est « exploratoire, non validée après correction
            ».{" "}
            {mode === "discovery" ? (
              <>Le risque de faux positif après correction ne passe pas le contrôle.</>
            ) : (
              <>
                La valeur corrigée vaut{" "}
                {formatEvidenceNumber(
                  metrics.correctedFalsePositiveRisk,
                )}
                .
              </>
            )}{" "}
            Aucune preuve prospective n’est incluse dans cette source. Un
            profit historique de{" "}
            {formatEvidenceUnits(metrics.profitUnits, true)} ne change pas ce
            verdict.
          </p>
        </div>
      </section>

      {mode === "discovery" ? null : (
        <section className="hu-section">
          <UniverseSectionHeading
            eyebrow="Comprendre les mesures"
            title="Les mots derrière les chiffres"
          />
          <div className="hu-explainer-grid">
            <MetricExplainer
              expert="Nombre d’appartenances strictes et dédupliquées pour cette règle."
              name="Occurrences historiques"
              simple="Le nombre de matchs réellement utilisés pour calculer le résultat."
            />
            <MetricExplainer
              expert="Étendue d’incertitude publiée par la campagne historique."
              name="Intervalle"
              simple="La zone d’incertitude autour du résultat historique brut."
            />
            <MetricExplainer
              expert="Valeur q recalculée sur l’ensemble des règles de la campagne."
              name="Risque de faux positif après correction"
              simple="Un garde-fou lorsque Robin explore beaucoup d’idées à la fois."
            />
            <MetricExplainer
              expert="Fenêtres temporelles testées sans faire entrer le futur dans leur apprentissage."
              name="Validation chronologique"
              simple="Robin avance dans le temps sans utiliser le futur pour expliquer le passé."
            />
          </div>
        </section>
      )}

      {mode === "expert" ? (
        <section className="hu-section hu-expert-proof">
          <UniverseSectionHeading
            eyebrow="Vue Expert"
            title="Données, contrat et provenance"
          />
          <dl className="hu-technical-grid">
            <div>
              <dt>Hash de règle</dt>
              <dd>
                <code>{evidence.provenance.ruleHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash des appartenances</dt>
              <dd>
                <code>{evidence.provenance.membershipSetHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash du jeu de données</dt>
              <dd>
                <code>{evidence.provenance.datasetHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash du résultat source</dt>
              <dd>
                <code>{evidence.provenance.sourceResultHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash de rejouabilité</dt>
              <dd>
                <code>{evidence.provenance.replayHash}</code>
              </dd>
            </div>
            <div>
              <dt>Révision Git historique</dt>
              <dd>
                <code>{evidence.provenance.historicalDataRevision}</code>
              </dd>
            </div>
            <div>
              <dt>Contrat du rapport</dt>
              <dd>
                <code>{evidence.provenance.reportSchemaVersion}</code>
              </dd>
            </div>
            <div>
              <dt>Portée de preuve</dt>
              <dd>
                <code>{evidence.evidenceScope}</code>
              </dd>
            </div>
            <div>
              <dt>Génération réconciliée</dt>
              <dd>{formatDateTime(evidence.provenance.generatedAt, true)}</dd>
            </div>
          </dl>
          <details className="hu-metric-explainer">
            <summary>
              <span>Conditions techniques exactes</span>
              <small>{evidence.conditions.length} conditions</small>
            </summary>
            <ol className="hu-technical-condition-list">
              {evidence.conditions.map((condition, index) => (
                <li key={`${condition.feature}-${index}`}>
                  <code>
                    {condition.feature} {condition.operator}{" "}
                    {JSON.stringify(condition.value)}
                  </code>
                  <small>
                    {condition.source} · {condition.availableAt}
                  </small>
                </li>
              ))}
            </ol>
          </details>
          <p>
            <Link
              className="hu-text-link"
              href="/hypotheses/classements"
            >
              Retour au classement borné
            </Link>
          </p>
        </section>
      ) : null}
    </>
  );
}
