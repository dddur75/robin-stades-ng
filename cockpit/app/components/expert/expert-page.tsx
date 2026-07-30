"use client";

import {
  expertData,
  operationalEvidence,
  presentationSystem,
} from "../../lib/presentation";
import {
  formatBytes,
  formatNumber,
  formatPercent,
  t,
} from "../../i18n";
import { statusPresentation } from "../../i18n/status-translations";
import { RichTable } from "../common/rich-table";
import {
  EvidenceNote,
  InlineLink,
  MetricCard,
  PageHeader,
  ProgressBar,
  SectionHeading,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { useViewMode, ViewModeSwitch } from "../common/view-mode";
import { HypothesisExplorer } from "./hypothesis-explorer";

function displayText(value: unknown) {
  return String(value ?? "—");
}

function sourceLabel(value: string) {
  const labels: Record<string, string> = {
    "LIVE SOURCE": "Source opérationnelle",
    "OOS HISTORICAL": "Historique hors échantillon",
    "LEGACY SOURCE": "Source historique",
    "NO OUTPUT": "Aucune sortie",
  };
  return labels[value] ?? displayText(value);
}

const absoluteInvariantOrder = [
  "NO_BET_DEFAULT",
  "REAL_BETS",
  "PRODUCTION_LOCKED",
];

const absoluteInvariantRows = Object.entries(operationalEvidence.invariants).sort(
  ([left], [right]) => {
    const leftIndex = absoluteInvariantOrder.indexOf(left);
    const rightIndex = absoluteInvariantOrder.indexOf(right);
    if (leftIndex === rightIndex) return left.localeCompare(right);
    if (leftIndex === -1) return 1;
    if (rightIndex === -1) return -1;
    return leftIndex - rightIndex;
  },
);

const datasetRows: Array<Record<string, unknown>> = expertData.datasets.map((row) => ({
  nom: row.name,
  version: row.version,
  lignes: row.rows,
  rencontres: row.fixtures,
  couverture: formatPercent(row.coverage),
  qualite: statusPresentation(row.quality).short,
  temporalite: displayText(row.temporalPolicy),
  statut: row.status,
  empreinte: row.sha256,
}));

const modelRows: Array<Record<string, unknown>> = expertData.models.map((row) => ({
  modele: row.name,
  version: row.version,
  jeu: "dataset" in row ? row.dataset : "—",
  logLoss: row.logLoss == null ? t("common.notApplicable") : Number(row.logLoss).toFixed(4),
  brier: row.brier == null ? t("common.notApplicable") : Number(row.brier).toFixed(4),
  calibration: "calibration" in row ? row.calibration : "—",
  statut: row.status,
  origine: sourceLabel(row.origin),
}));

const backtestRows: Array<Record<string, unknown>> = expertData.backtests.map((row) => ({
  strategie: row.strategy,
  marche: row.market,
  paris: row.bets,
  roi: formatPercent(row.roi),
  resultat: `${formatNumber(row.profit_units, 2)} u`,
  repli: `${formatNumber(row.max_drawdown_units, 2)} u`,
  pAjustee: formatNumber(row.adjusted_p_value, 4),
  statut: row.status,
  origine: sourceLabel(row.origin),
}));

const qualityRows: Array<Record<string, unknown>> = expertData.qualityChecks.map((row) => ({
  controle: displayText(row.check),
  resultat: statusPresentation(row.status).short,
  valeur: displayText(row.value),
  seuil: displayText(row.threshold),
  origine: sourceLabel(row.origin),
}));

const externalReadinessRows: Array<Record<string, unknown>> =
  expertData.externalValidation.readiness.map((row) => ({
    competition: row.competition,
    saisons: Array.isArray(row.seasons)
      ? row.seasons.join("–")
      : displayText(row.seasons),
    equipes: row.teams,
    joueurs: row.players,
    qualite: statusPresentation(row.quality).short,
    temporalite: statusPresentation(row.temporality).short,
    gate: statusPresentation(row.gates.EXTERNAL_VALIDATION_GATE.status).short,
    code: row.gates.EXTERNAL_VALIDATION_GATE.status,
  }));

const leaveOneLeagueOutRows: Array<Record<string, unknown>> =
  expertData.externalValidation.leaveOneLeagueOut.map((row) => ({
    ligue: row.held_out_competition,
    entrainement: row.training_competitions.join(" · "),
    rencontres: row.paired_fixtures,
    logLoss: Number(row.metrics.log_loss).toFixed(4),
    brier: Number(row.metrics.brier_score).toFixed(4),
    calibration: displayText(row.calibration_stability),
    statut: row.status,
  }));

const playerGeneralizationRows: Array<Record<string, unknown>> =
  expertData.externalValidation.playerGeneralization.map((row) => ({
    competition: row.competition,
    resultat: statusPresentation(row.status).short,
    raison: displayText(row.reason),
    statut: row.scientific_status,
  }));

export function ExpertPage() {
  const { isExpert } = useViewMode();

  return (
    <>
      <PageHeader
        eyebrow={t("expert.eyebrow")}
        subtitle={t("expert.subtitle")}
        title={t("expert.title")}
      >
        <ViewModeSwitch />
      </PageHeader>

      {!isExpert ? (
        <>
          <section className="expert-gate">
            <span aria-hidden="true">⌘</span>
            <h2>{t("expert.modeRequired")}</h2>
            <p>
              L’espace Expert conserve les métriques avancées, les empreintes,
              la provenance, le stockage et les données brutes. Le passage de vue
              ne modifie jamais les données.
            </p>
            <ViewModeSwitch />
          </section>
          <section className="expert-preview-grid">
            {[
              [t("expert.data.title"), t("expert.data.subtitle"), "◫"],
              [t("expert.models.title"), t("expert.models.subtitle"), "◇"],
              [t("expert.simulations.title"), t("expert.simulations.subtitle"), "↺"],
              [t("expert.costs.title"), t("expert.costs.subtitle"), "◔"],
              [t("expert.system.title"), t("expert.system.subtitle"), "⌘"],
            ].map(([title, subtitle, icon]) => (
              <article key={title}>
                <span aria-hidden="true">{icon}</span>
                <h2>{title}</h2>
                <p>{subtitle}</p>
              </article>
            ))}
          </section>
        </>
      ) : (
        <div className="expert-content">
          <section className="expert-section" id="hypotheses">
            <SectionHeading
              subtitle="Projection paginée des 700 règles Jalon 10; une seule page de 50 règles est chargée à la fois."
              title="Explorateur des hypothèses"
            />
            <EvidenceNote>
              Les tris et métriques restent exploratoires. Un ROI historique brut
              ne constitue ni une validation, ni un rendement attendu.
            </EvidenceNote>
            <HypothesisExplorer />
          </section>

          <section className="expert-section" id="donnees">
            <SectionHeading
              action={
                <InlineLink href="/expert/qualite-donnees">
                  Ouvrir les diagnostics de disponibilité
                </InlineLink>
              }
              subtitle={t("expert.data.subtitle")}
              title={t("expert.data.title")}
            />
            <div className="metrics-grid">
              <MetricCard detail="catalogués" label="Jeux de données" tone="blue" value={formatNumber(expertData.datasets.length)} />
              <MetricCard detail="contrôles publiés" label="Qualité" tone="green" value={formatNumber(expertData.qualityChecks.length)} />
              <MetricCard detail="résolu" label="Incidents" value={formatNumber(expertData.incidents.length)} />
              <MetricCard detail="empreintes append-only" label="Événements de preuve" tone="violet" value={formatNumber(operationalEvidence.ledger.events)} />
            </div>
            <div className="section-card">
              <RichTable
                caption="Jeux de données et qualité temporelle"
                columns={[
                  { key: "nom", label: "Jeu de données" },
                  { key: "lignes", label: "Lignes" },
                  { key: "rencontres", label: "Rencontres" },
                  { key: "couverture", label: "Couverture" },
                  { key: "qualite", label: "Qualité" },
                  { key: "temporalite", label: "Temporalité" },
                  { key: "statut", label: "État technique" },
                  { key: "empreinte", label: "SHA-256" },
                ]}
                filename="robin-jeux-de-donnees-expert.csv"
                rows={datasetRows}
              />
            </div>
            <div className="section-card">
              <SectionHeading title="Contrôles de qualité" />
              <RichTable
                caption="Contrôles, seuils et provenance"
                columns={[
                  { key: "controle", label: "Contrôle" },
                  { key: "resultat", label: "Résultat" },
                  { key: "valeur", label: "Valeur" },
                  { key: "seuil", label: "Seuil" },
                  { key: "origine", label: "Provenance" },
                ]}
                filename="robin-qualite-expert.csv"
                rows={qualityRows}
              />
            </div>
          </section>

          <section className="expert-section" id="modeles">
            <SectionHeading subtitle={t("expert.models.subtitle")} title={t("expert.models.title")} />
            <div className="section-card">
              <RichTable
                caption="Comparaison des modèles"
                columns={[
                  { key: "modele", label: "Modèle" },
                  { key: "jeu", label: "Jeu de données" },
                  { key: "logLoss", label: "Log Loss" },
                  { key: "brier", label: "Score de Brier" },
                  { key: "calibration", label: "Calibration" },
                  { key: "statut", label: "État technique" },
                  { key: "origine", label: "Provenance" },
                ]}
                filename="robin-modeles-expert.csv"
                rows={modelRows}
              />
            </div>
            <div className="section-card">
              <SectionHeading title="Comparaison Log Loss" subtitle="Plus bas est meilleur, uniquement sur des échantillons comparables." />
              <div className="bar-chart" role="img" aria-label="Comparaison textuelle des Log Loss des modèles disponibles">
                {expertData.models.filter((row) => row.logLoss != null).slice(0, 5).map((row) => (
                  <div key={row.name}>
                    <span>{row.name}</span>
                    <i style={{ width: `${Math.min(100, Number(row.logLoss) / 2 * 100)}%` }} />
                    <strong>{Number(row.logLoss).toFixed(4)}</strong>
                  </div>
                ))}
              </div>
              <p className="chart-summary">
                Résumé : ces scores historiques ne constituent pas une performance prospective et ne déclenchent aucune promotion.
              </p>
            </div>
            <div className="section-card">
              <SectionHeading
                subtitle="Les transferts entre ligues restent séparés de toute promotion et conservent leurs gates."
                title={t("expert.external.title")}
              />
              <div className="metrics-grid">
                <MetricCard
                  detail={statusPresentation(expertData.externalValidation.status).short}
                  label={t("expert.external.readiness")}
                  tone="blue"
                  value={formatNumber(expertData.externalValidation.readiness.length)}
                />
                <MetricCard
                  detail="comparaisons appariées"
                  label={t("expert.external.transfer")}
                  tone="violet"
                  value={formatNumber(expertData.externalValidation.comparisons.length)}
                />
                <MetricCard
                  detail="ligues laissées de côté"
                  label={t("expert.external.leaveOneOut")}
                  value={formatNumber(expertData.externalValidation.leaveOneLeagueOut.length)}
                />
                <MetricCard
                  detail={statusPresentation(expertData.externalValidation.strategies.status).short}
                  label={t("expert.external.strategies")}
                  tone="orange"
                  value={formatNumber(expertData.externalValidation.strategies.hypotheses)}
                />
              </div>
              <RichTable
                caption={t("expert.external.readiness")}
                columns={[
                  { key: "competition", label: "Compétition" },
                  { key: "saisons", label: "Saisons" },
                  { key: "equipes", label: "Équipes" },
                  { key: "joueurs", label: "Joueurs" },
                  { key: "qualite", label: "Qualité" },
                  { key: "temporalite", label: "Temporalité" },
                  { key: "gate", label: "Vérification externe" },
                  { key: "code", label: "État technique" },
                ]}
                filename="robin-validation-externe-expert.csv"
                rows={externalReadinessRows}
              />
            </div>
            <div className="two-columns">
              <article className="section-card">
                <SectionHeading title={t("expert.external.leaveOneOut")} />
                <RichTable
                  caption={t("expert.external.leaveOneOut")}
                  columns={[
                    { key: "ligue", label: "Ligue évaluée" },
                    { key: "entrainement", label: "Ligues d’entraînement" },
                    { key: "rencontres", label: "Rencontres" },
                    { key: "logLoss", label: "Log Loss" },
                    { key: "brier", label: "Score de Brier" },
                    { key: "calibration", label: "Calibration" },
                    { key: "statut", label: "État technique" },
                  ]}
                  filename="robin-validation-ligue-laissee-expert.csv"
                  rows={leaveOneLeagueOutRows}
                />
              </article>
              <article className="section-card">
                <SectionHeading title={t("expert.external.players")} />
                <RichTable
                  caption={t("expert.external.players")}
                  columns={[
                    { key: "competition", label: "Compétition" },
                    { key: "resultat", label: "Résultat" },
                    { key: "raison", label: "Raison" },
                    { key: "statut", label: "État scientifique" },
                  ]}
                  filename="robin-generalisation-joueurs-expert.csv"
                  rows={playerGeneralizationRows}
                />
              </article>
            </div>
            <div className="section-card">
              <SectionHeading title={t("expert.external.package")} />
              <StatusBadge
                showTechnical
                value={expertData.externalValidation.package.status}
              />
              <TechnicalList
                rows={[
                  {
                    label: "Paquet",
                    value: <code>{expertData.externalValidation.package.package}</code>,
                  },
                  {
                    label: "Empreinte",
                    value: <code>{expertData.externalValidation.package.package_hash}</code>,
                  },
                  {
                    label: "Prédictions externes",
                    value: expertData.externalValidation.predictions,
                  },
                  {
                    label: "Appels fournisseur",
                    value: expertData.externalValidation.providerCalls,
                  },
                  {
                    label: "Crédits consommés",
                    value: expertData.externalValidation.quotaConsumed,
                  },
                ]}
              />
            </div>
          </section>

          <section className="expert-section" id="simulations">
            <SectionHeading subtitle={t("expert.simulations.subtitle")} title={t("expert.simulations.title")} />
            <div className="section-card">
              <RichTable
                caption="Simulations historiques hors échantillon"
                columns={[
                  { key: "strategie", label: "Stratégie" },
                  { key: "marche", label: "Marché" },
                  { key: "paris", label: "Paris simulés" },
                  { key: "roi", label: "ROI historique" },
                  { key: "resultat", label: "Résultat" },
                  { key: "repli", label: "Repli maximal" },
                  { key: "pAjustee", label: "p ajustée" },
                  { key: "statut", label: "État technique" },
                ]}
                filename="robin-simulations-historiques-expert.csv"
                rows={backtestRows}
              />
            </div>
            <EvidenceNote>
              Les simulations historiques restent séparées des tests prospectifs,
              des décisions simulées et des résultats réglés.
            </EvidenceNote>
          </section>

          <section className="expert-section" id="couts">
            <SectionHeading subtitle={t("expert.costs.subtitle")} title={t("expert.costs.title")} />
            <div className="metrics-grid">
              <MetricCard detail={`sur ${formatNumber(expertData.quota.provider_limit)}`} label="Crédits historiques utilisés" value={formatNumber(expertData.quota.used_after_activation)} />
              <MetricCard detail={`${expertData.quota.reserve_pct} % protégés`} label="Réserve" tone="green" value={formatNumber(expertData.quota.reserve_credits)} />
              <MetricCard detail="projection informative" label="Plafond opérationnel" tone="orange" value={formatNumber(expertData.quota.operational_ceiling)} />
              <MetricCard detail="aucun achat déclenché" label="Coût réel observé" value="0 €" />
            </div>
            <div className="section-card">
              <ProgressBar label={`Quota disponible · ${formatNumber(expertData.quota.remaining_after_activation)} crédits`} value={expertData.quota.remaining_after_activation / expertData.quota.provider_limit} />
              <TechnicalList rows={[
                { label: "Crédits par snapshot", value: expertData.quota.credits_per_snapshot },
                { label: "Prévision mensuelle", value: `${formatNumber(expertData.quota.forecast_credits_per_month)} crédits` },
                { label: "Stockage d’artefacts", value: formatBytes(expertData.quota.artifact_storage_bytes_retained) },
                { label: "Coût fournisseur observé", value: `${formatNumber(expertData.quota.estimated_provider_cost_eur, 2)} €` },
              ]} />
            </div>
          </section>

          <section className="expert-section" id="systeme">
            <SectionHeading subtitle={t("expert.system.subtitle")} title={t("expert.system.title")} />
            <div className="system-grid">
              <article className="section-card">
                <h3>R2</h3>
                <StatusBadge value={operationalEvidence.r2.replayStatus} showTechnical />
                <TechnicalList rows={[
                  { label: "Objets", value: operationalEvidence.r2.objects },
                  { label: "Volume", value: formatBytes(operationalEvidence.r2.bytes) },
                  { label: "Retard", value: operationalEvidence.r2.lag },
                  { label: "Suppressions", value: operationalEvidence.r2.deletions },
                ]} />
              </article>
              <article className="section-card">
                <h3>PostgreSQL</h3>
                <StatusBadge value={operationalEvidence.postgresql.reconstructionStatus} showTechnical />
                <TechnicalList rows={[
                  { label: "Migration", value: <code>{operationalEvidence.postgresql.migration}</code> },
                  { label: "Tables", value: operationalEvidence.postgresql.tables },
                  { label: "Insertions", value: operationalEvidence.postgresql.inserts },
                  { label: "Doublons évités", value: operationalEvidence.postgresql.duplicatesAvoided },
                ]} />
              </article>
              <article className="section-card invariants-card">
                <h3>Invariants absolus</h3>
                <ul>
                  {absoluteInvariantRows.map(([key, value]) => (
                    <li key={key}><code>{key}={String(value)}</code><span>verrouillé</span></li>
                  ))}
                </ul>
              </article>
            </div>
            <div className="section-card">
              <SectionHeading title="Provenance complète" />
              <TechnicalList rows={[
                { label: "Artefact", value: <code>{operationalEvidence.sourceRun}</code> },
                { label: "Révision", value: <code>{operationalEvidence.sourceRevision}</code> },
                { label: "Workflow", value: <code>{operationalEvidence.sourceWorkflow}</code> },
                { label: "Généré à (UTC)", value: <code>{operationalEvidence.generatedAt}</code> },
                { label: "Âge du snapshot", value: operationalEvidence.freshness.ageMinutes == null ? t("common.notApplicable") : `${formatNumber(operationalEvidence.freshness.ageMinutes)} min` },
                { label: "Fraîcheur", value: <StatusBadge value={operationalEvidence.freshness.status} showTechnical /> },
                { label: "Motif de fraîcheur", value: operationalEvidence.freshness.reason },
                { label: "Tête du registre", value: <code>{operationalEvidence.ledger.headHash}</code> },
                { label: "Payloads PostgreSQL", value: operationalEvidence.postgresql.payloadBodyRows },
                { label: "Couverture des statuts", value: `${formatPercent(presentationSystem.statusCoverage.percentage)} · ${presentationSystem.statusCoverage.translated}/${presentationSystem.statusCoverage.total}` },
                { label: "Statuts inconnus", value: presentationSystem.statusCoverage.unknown.join(" · ") || "Aucun" },
                { label: "Corrections d’encodage legacy", value: presentationSystem.encodingCorrections.count },
                { label: "Nettoyeur legacy actif", value: presentationSystem.encodingCorrections.cleanerEnabled ? "Oui" : "Non" },
              ]} />
            </div>
          </section>
        </div>
      )}
    </>
  );
}
