import {
  formatDateTime,
  formatNumber,
  formatPercent,
  t,
} from "../../i18n";
import {
  leagueSummaries,
  prequentialLearning,
} from "../../lib/presentation";
import { RichTable } from "../common/rich-table";
import {
  EmptyState,
  EvidenceNote,
  MetricCard,
  PageHeader,
  SectionHeading,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

function roleLabel(value: string) {
  return value === "REFERENCE" ? "Référence" : "Challenger";
}

function scopeLabel(value: string) {
  const labels: Record<string, string> = {
    GLOBAL_FIVE_LEAGUES: "Cinq championnats",
    LIGUE_1: "Ligue 1",
    PREMIER_LEAGUE: "Premier League",
    LIGA: "Liga",
    BUNDESLIGA: "Bundesliga",
    SERIE_A: "Serie A",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

const predictionRows: Array<Record<string, unknown>> =
  prequentialLearning.predictions.map((prediction) => ({
    prediction: prediction.predictionId,
    rencontre: prediction.match,
    ligue: prediction.competition,
    marche: prediction.market,
    cutoff: prediction.cutoffName,
    cutoffAt: prediction.cutoffAt
      ? formatDateTime(prediction.cutoffAt, true)
      : "—",
    modele: `${prediction.modelId} · ${prediction.modelVersion}`,
    statut: prediction.status,
    features: prediction.featureSnapshotHash ?? "—",
    payload: prediction.payloadHash ?? "—",
  }));

const modelRows: Array<Record<string, unknown>> =
  prequentialLearning.models.map((model) => ({
    modele: model.name,
    role: roleLabel(model.role),
    portee: scopeLabel(model.scope),
    version: model.version,
    statut: model.status,
    cutoff: model.trainingCutoff ?? "—",
    contrat: model.featureContractHash ?? "—",
    artefact: model.artifactHash ?? "—",
    revision: model.codeRevision ?? "—",
  }));

const manifestRows: Array<Record<string, unknown>> =
  prequentialLearning.manifests.map((manifest) => ({
    manifest: manifest.manifestId,
    modele: manifest.modelId,
    version: manifest.modelVersion,
    cree: manifest.createdAt
      ? formatDateTime(manifest.createdAt, true)
      : "—",
    rencontres: manifest.fixtureCount,
    ligues: manifest.leagues.join(" · "),
    dataset: manifest.datasetHash ?? "—",
    contrat: manifest.featureContractHash ?? "—",
    artefact: manifest.artifactHash ?? "—",
    statut: manifest.status,
  }));

const ledgerRows: Array<Record<string, unknown>> =
  prequentialLearning.ledger.recent.map((event) => ({
    sequence: event.sequence,
    evenement: event.kind,
    date: event.recordedAt
      ? formatDateTime(event.recordedAt, true)
      : "—",
    rencontre: event.fixtureId ?? "—",
    modele: event.modelId ?? "—",
    version: event.modelVersion ?? "—",
    empreinte: event.eventHash ?? "—",
    precedente: event.previousHash ?? "—",
  }));

export function LearningPage() {
  const training = prequentialLearning.training;
  const comparison = prequentialLearning.comparison;
  const missingTrainingFixtures = Math.max(
    0,
    training.minimumFixtures - training.newSupport,
  );
  const hasComparison =
    prequentialLearning.settledFixtures > 0
    && [
      comparison.logLossReference,
      comparison.logLossChallenger,
      comparison.brierReference,
      comparison.brierChallenger,
    ].some((value) => value !== null);

  const flow = [
    {
      label: t("learning.flow.features"),
      detail: "Valeurs, disponibilité, provenance et cutoff",
      status:
        prequentialLearning.nextPrediction
        || prequentialLearning.frozenPredictions > 0
          ? "CAPTURED"
          : "NOT_DUE",
    },
    {
      label: t("learning.flow.prediction"),
      detail: "Référence et challenger restent immuables",
      status:
        prequentialLearning.frozenPredictions > 0 ? "FROZEN" : "NOT_DUE",
    },
    {
      label: t("learning.flow.result"),
      detail: "Uniquement après un statut final vérifié",
      status:
        prequentialLearning.settledFixtures > 0
          ? "SETTLED"
          : "WAITING_FOR_RESULTS",
    },
    {
      label: t("learning.flow.training"),
      detail: "Le match réglé devient admissible pour une version future",
      status: training.status,
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow={t("learning.eyebrow")}
        subtitle={t("learning.subtitle")}
        title={t("learning.title")}
      >
        <div className="hero-statuses">
          <StatusBadge value={prequentialLearning.status} />
          <StatusBadge value={prequentialLearning.promotion.status} />
        </div>
      </PageHeader>

      <section className="learning-principle">
        <span aria-hidden="true">↻</span>
        <div>
          <p className="eyebrow">Règle temporelle essentielle</p>
          <h2>{t("learning.principle")}</h2>
          <p>
            Les essais historiques et synthétiques vérifient la mécanique,
            mais ne sont jamais comptés comme une performance réelle.
          </p>
        </div>
      </section>

      <section
        aria-label="Indicateurs de l’apprentissage en direct"
        className="metrics-grid learning-metrics"
      >
        <MetricCard
          detail={`${formatNumber(prequentialLearning.rejectedPredictions)} rejetée(s) et tracée(s)`}
          icon="❄"
          label={t("learning.metrics.frozen")}
          tone="blue"
          value={formatNumber(prequentialLearning.frozenPredictions)}
        />
        <MetricCard
          detail={`${formatNumber(prequentialLearning.models.length)} version(s) publiée(s)`}
          icon="◇"
          label={t("learning.metrics.models")}
          tone="violet"
          value={formatNumber(prequentialLearning.activeModels)}
        />
        <MetricCard
          detail={`${formatNumber(prequentialLearning.settledPredictions)} prédiction(s) scorée(s)`}
          icon="✓"
          label={t("learning.metrics.settled")}
          tone="green"
          value={formatNumber(prequentialLearning.settledFixtures)}
        />
        <MetricCard
          detail={`${formatNumber(training.minimumFixtures)} rencontres et ${formatNumber(training.minimumLeagues)} ligues minimum`}
          icon="◫"
          label={t("learning.metrics.support")}
          tone="orange"
          value={`${formatNumber(training.newSupport)} / ${formatNumber(training.minimumFixtures)}`}
        />
        <MetricCard
          detail={
            prequentialLearning.nextPrediction
              ? `${prequentialLearning.nextPrediction.cutoffName} · ${prequentialLearning.nextPrediction.match}`
              : "Aucun cutoff réel n’est encore dû"
          }
          icon="◷"
          label={t("learning.metrics.nextPrediction")}
          value={
            prequentialLearning.nextPrediction
              ? formatDateTime(prequentialLearning.nextPrediction.cutoffAt, true)
              : "En attente"
          }
        />
        <MetricCard
          detail={
            training.nextPossibleAt
              ? formatDateTime(training.nextPossibleAt, true)
              : `${formatNumber(missingTrainingFixtures)} nouveau(x) règlement(s) requis`
          }
          icon="↻"
          label={t("learning.metrics.nextTraining")}
          value={training.nextPossibleAt ? "Planifiable" : "Différé"}
        />
      </section>

      <section className="section-block">
        <SectionHeading
          subtitle={t("learning.flow.subtitle")}
          title={t("learning.flow.title")}
        />
        <div className="learning-flow">
          {flow.map((step, index) => (
            <article key={step.label}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <h3>{step.label}</h3>
                <p>{step.detail}</p>
              </div>
              <StatusBadge value={step.status} />
            </article>
          ))}
        </div>
      </section>

      <section className="section-block">
        <SectionHeading
          subtitle={t("learning.models.subtitle")}
          title={t("learning.models.title")}
        />
        {prequentialLearning.models.length ? (
          <div className="learning-model-grid">
            {prequentialLearning.models.map((model) => (
              <article className="feature-card" key={`${model.modelId}:${model.version}`}>
                <div className="learning-model-head">
                  <span>{roleLabel(model.role)}</span>
                  <StatusBadge value={model.status} />
                </div>
                <h3>{model.name}</h3>
                <p>{scopeLabel(model.scope)}</p>
                <dl>
                  <div>
                    <dt>Version</dt>
                    <dd>{model.version}</dd>
                  </div>
                  <div>
                    <dt>Entraînement arrêté au</dt>
                    <dd>
                      {model.trainingCutoff
                        ? formatDateTime(model.trainingCutoff, true)
                        : "Non applicable"}
                    </dd>
                  </div>
                </dl>
                <ExpertOnly>
                  <TechnicalList
                    rows={[
                      { label: "Identifiant", value: <code>{model.modelId}</code> },
                      {
                        label: "Contrat de features",
                        value: <code>{model.featureContractHash ?? "Non publié"}</code>,
                      },
                      {
                        label: "Artefact",
                        value: <code>{model.artifactHash ?? "Non publié"}</code>,
                      },
                      {
                        label: "Révision",
                        value: <code>{model.codeRevision ?? "Non publiée"}</code>,
                      },
                    ]}
                  />
                </ExpertOnly>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            text="Le registre réel attend la publication de ses premières versions gelées. Aucun modèle historique n’est substitué."
            title="Aucune version réelle publiée"
          />
        )}
      </section>

      <section className="two-columns">
        <article className="section-card">
          <SectionHeading
            subtitle={t("learning.comparison.subtitle")}
            title={t("learning.comparison.title")}
          />
          {hasComparison ? (
            <div className="learning-comparison">
              <div>
                <span>Log Loss</span>
                <strong>
                  {comparison.logLossReference == null
                    ? "Non applicable"
                    : formatNumber(comparison.logLossReference, 4)}
                </strong>
                <strong>
                  {comparison.logLossChallenger == null
                    ? "Non applicable"
                    : formatNumber(comparison.logLossChallenger, 4)}
                </strong>
              </div>
              <div>
                <span>Score de Brier</span>
                <strong>
                  {comparison.brierReference == null
                    ? "Non applicable"
                    : formatNumber(comparison.brierReference, 4)}
                </strong>
                <strong>
                  {comparison.brierChallenger == null
                    ? "Non applicable"
                    : formatNumber(comparison.brierChallenger, 4)}
                </strong>
              </div>
              <div className="learning-comparison-legend">
                <span>Référence</span>
                <span>Challenger</span>
              </div>
              <EvidenceNote>
                Couverture {formatPercent(comparison.coverage)} · données
                manquantes {formatPercent(comparison.missingness)}.
              </EvidenceNote>
            </div>
          ) : (
            <EmptyState
              text={t("learning.empty.comparison.text")}
              title={t("learning.empty.comparison.title")}
            />
          )}
        </article>

        <article className="section-card promotion-lock-card">
          <span aria-hidden="true">▣</span>
          <SectionHeading title={t("learning.promotion.title")} />
          <p>{t("learning.promotion.text")}</p>
          <StatusBadge value={prequentialLearning.promotion.status} />
          <ul className="compact-list">
            <li>Support prospectif suffisant requis</li>
            <li>Calibration non dégradée</li>
            <li>Avantage non concentré sur une ligue</li>
            <li>Contrôles de fuite et contrôles négatifs verts</li>
          </ul>
        </article>
      </section>

      <section className="section-block">
        <SectionHeading
          subtitle={t("learning.leagues.subtitle")}
          title={t("learning.leagues.title")}
        />
        <div className="learning-league-grid">
          {leagueSummaries.map((league) => {
            const result = prequentialLearning.leagueResults.find(
              (item) => item.competition === league.competition,
            );
            const settled = result?.settledFixtures ?? 0;
            return (
              <article key={league.competition}>
                <div>
                  <h3>{league.competition}</h3>
                  <StatusBadge value={result?.status ?? "WAITING_FOR_RESULTS"} />
                </div>
                <dl>
                  <div>
                    <dt>Prédictions gelées</dt>
                    <dd>{formatNumber(result?.predictions ?? 0)}</dd>
                  </div>
                  <div>
                    <dt>Rencontres réglées</dt>
                    <dd>{formatNumber(settled)}</dd>
                  </div>
                  <div>
                    <dt>Log Loss challenger</dt>
                    <dd>
                      {settled > 0 && result?.logLossChallenger != null
                        ? formatNumber(result.logLossChallenger, 4)
                        : "Non applicable"}
                    </dd>
                  </div>
                  <div>
                    <dt>Score de Brier challenger</dt>
                    <dd>
                      {settled > 0 && result?.brierChallenger != null
                        ? formatNumber(result.brierChallenger, 4)
                        : "Non applicable"}
                    </dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
      </section>

      {prequentialLearning.frozenPredictions === 0 ? (
        <section className="section-card">
          <EmptyState
            text={t("learning.empty.predictions.text")}
            title={t("learning.empty.predictions.title")}
          />
        </section>
      ) : null}

      <ExpertOnly>
        <section className="expert-section" id="apprentissage-predictions">
          <SectionHeading title={t("learning.expert.predictions")} />
          {predictionRows.length ? (
            <div className="section-card">
              <RichTable
                caption="Prédictions préquentielles immuables"
                columns={[
                  { key: "prediction", label: "Prédiction" },
                  { key: "rencontre", label: "Rencontre" },
                  { key: "ligue", label: "Ligue" },
                  { key: "marche", label: "Marché" },
                  { key: "cutoff", label: "Cutoff" },
                  { key: "cutoffAt", label: "Heure limite" },
                  { key: "modele", label: "Modèle et version" },
                  { key: "statut", label: "État technique" },
                  { key: "features", label: "Features SHA-256" },
                  { key: "payload", label: "Payload SHA-256" },
                ]}
                filename="robin-predictions-prequentielles.csv"
                rows={predictionRows}
              />
            </div>
          ) : (
            <EmptyState
              text={t("learning.empty.predictions.text")}
              title={t("learning.empty.predictions.title")}
            />
          )}
        </section>

        <section className="expert-section" id="apprentissage-modeles">
          <SectionHeading title={t("learning.expert.models")} />
          <div className="section-card">
            <RichTable
              caption="Versions immuables des modèles préquentiels"
              columns={[
                { key: "modele", label: "Modèle" },
                { key: "role", label: "Rôle" },
                { key: "portee", label: "Portée" },
                { key: "version", label: "Version" },
                { key: "statut", label: "État technique" },
                { key: "cutoff", label: "Cutoff d’entraînement" },
                { key: "contrat", label: "Contrat SHA-256" },
                { key: "artefact", label: "Artefact SHA-256" },
                { key: "revision", label: "Révision" },
              ]}
              filename="robin-modeles-prequentiels.csv"
              rows={modelRows}
            />
          </div>
        </section>

        <section className="expert-section" id="apprentissage-entrainement">
          <SectionHeading title={t("learning.expert.training")} />
          <div className="section-card">
            <TechnicalList
              rows={[
                { label: "État", value: <StatusBadge showTechnical value={training.status} /> },
                { label: "Support nouveau", value: training.newSupport },
                { label: "Rencontres éligibles", value: training.eligibleFixtures },
                { label: "Ligues représentées", value: training.representedLeagues },
                { label: "Minimum de rencontres", value: training.minimumFixtures },
                { label: "Minimum de ligues", value: training.minimumLeagues },
                { label: "Dernière version", value: <code>{training.lastVersion ?? "Aucune"}</code> },
                {
                  label: "Dernier manifest",
                  value: <code>{training.latestManifestHash ?? "Aucun"}</code>,
                },
                { label: "Entraînements réels", value: prequentialLearning.realTrainingRuns },
              ]}
            />
          </div>
          {manifestRows.length ? (
            <div className="section-card">
              <RichTable
                caption="Manifests d’entraînement versionnés"
                columns={[
                  { key: "manifest", label: "Manifest" },
                  { key: "modele", label: "Modèle" },
                  { key: "version", label: "Version" },
                  { key: "cree", label: "Créé le" },
                  { key: "rencontres", label: "Rencontres" },
                  { key: "ligues", label: "Ligues" },
                  { key: "dataset", label: "Dataset SHA-256" },
                  { key: "contrat", label: "Contrat SHA-256" },
                  { key: "artefact", label: "Artefact SHA-256" },
                  { key: "statut", label: "État technique" },
                ]}
                filename="robin-manifests-entrainement.csv"
                rows={manifestRows}
              />
            </div>
          ) : (
            <EmptyState
              text="Aucun entraînement réel n’a encore créé de manifest."
              title="Aucun manifest réel"
            />
          )}
        </section>

        <section className="expert-section" id="apprentissage-ledger">
          <SectionHeading title={t("learning.expert.ledger")} />
          <div className="section-card">
            <TechnicalList
              rows={[
                {
                  label: "Statut",
                  value: <StatusBadge showTechnical value={prequentialLearning.ledger.status} />,
                },
                { label: "Événements", value: prequentialLearning.ledger.events },
                {
                  label: "Tête de chaîne",
                  value: <code>{prequentialLearning.ledger.headHash}</code>,
                },
                {
                  label: "Origine",
                  value: <code>{prequentialLearning.origin}</code>,
                },
                {
                  label: "Généré à",
                  value: <code>{prequentialLearning.generatedAt}</code>,
                },
              ]}
            />
          </div>
          {ledgerRows.length ? (
            <div className="section-card">
              <RichTable
                caption="Derniers événements append-only"
                columns={[
                  { key: "sequence", label: "Séquence" },
                  { key: "evenement", label: "Événement" },
                  { key: "date", label: "Date" },
                  { key: "rencontre", label: "Rencontre" },
                  { key: "modele", label: "Modèle" },
                  { key: "version", label: "Version" },
                  { key: "empreinte", label: "Empreinte" },
                  { key: "precedente", label: "Empreinte précédente" },
                ]}
                filename="robin-ledger-prequentiel.csv"
                rows={ledgerRows}
              />
            </div>
          ) : (
            <EmptyState
              text="La tête de chaîne n’a encore reçu aucun événement réel."
              title="Ledger réel vide"
            />
          )}
          <div className="section-card">
            <SectionHeading title="Invariants de sécurité" />
            <TechnicalList
              rows={Object.entries(prequentialLearning.invariants).map(
                ([key, value]) => ({
                  label: key,
                  value: <code>{String(value)}</code>,
                }),
              )}
            />
          </div>
        </section>
      </ExpertOnly>
    </>
  );
}
