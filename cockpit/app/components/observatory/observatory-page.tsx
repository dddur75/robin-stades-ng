import {
  formatBytes,
  formatDateTime,
  formatNumber,
  formatPercent,
  t,
} from "../../i18n";
import {
  dataFamilyLabels,
  gateRows,
  matches,
  nextCaptures,
  operationalEvidence,
  type CoverageState,
} from "../../lib/presentation";
import {
  EvidenceNote,
  MetricCard,
  PageHeader,
  ProgressBar,
  SectionHeading,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { ExpertOnly } from "../common/view-mode";

const matrixFamilies = [
  "FIXTURE",
  "TEAM",
  "SQUAD",
  "PLAYER_STATUS",
  "INJURY",
  "LINEUP",
  "FORMATION",
  "ODDS",
] as const;

const stateLabels: Record<CoverageState, string> = {
  captured: t("common.captured"),
  upcoming: t("common.upcoming"),
  empty: t("common.empty"),
  blocked: t("common.blocked"),
  late: t("common.late"),
  error: t("common.error"),
};

export function ObservatoryPage() {
  return (
    <>
      <PageHeader
        eyebrow={t("observatory.eyebrow")}
        subtitle={t("observatory.subtitle")}
        title={t("observatory.title")}
      >
        <StatusBadge value={operationalEvidence.status} />
      </PageHeader>

      <section className="metrics-grid observatory-metrics" aria-label="Indicateurs de l’observatoire">
        <MetricCard detail="Ligue 1" icon="◉" label={t("observatory.metrics.fixtures")} tone="blue" value={formatNumber(operationalEvidence.fixtures)} />
        <MetricCard detail="politique révisée" icon="◫" label={t("observatory.metrics.activeWindows")} tone="green" value={formatNumber(operationalEvidence.activeWindows)} />
        <MetricCard detail="à cet instant" icon="◷" label={t("observatory.metrics.dueWindows")} value={formatNumber(operationalEvidence.dueWindows)} />
        <MetricCard detail="vérifiées dans R2" icon="✓" label={t("observatory.metrics.physical")} tone="green" value={formatNumber(operationalEvidence.physicalEvidence)} />
        <MetricCard detail="collecte en attente" icon="◇" label={t("observatory.metrics.deep")} tone="violet" value={formatNumber(operationalEvidence.deepObservations)} />
        <MetricCard detail="aucun incident actif" icon="!" label={t("observatory.metrics.errors")} value={formatNumber(operationalEvidence.errors)} />
      </section>

      <section className="section-card">
        <SectionHeading
          subtitle={t("observatory.timeline.subtitle")}
          title={t("observatory.timeline.title")}
        />
        <ol className="horizontal-timeline">
          {nextCaptures.slice(0, 5).map((capture, index) => (
            <li key={capture.id}>
              <div>
                <span>{index + 1}</span>
                {index < 4 ? <i /> : null}
              </div>
              <time dateTime={capture.dueAt}>{formatDateTime(capture.dueAt, true)}</time>
              <strong>{capture.match}</strong>
              <small>{dataFamilyLabels[capture.family]}</small>
              <StatusBadge value={capture.status} />
            </li>
          ))}
        </ol>
      </section>

      <section className="section-card coverage-matrix-section">
        <SectionHeading
          subtitle={t("observatory.matrix.subtitle")}
          title={t("observatory.matrix.title")}
        />
        <div className="coverage-legend" aria-label="Légende">
          {(Object.keys(stateLabels) as CoverageState[]).map((state) => (
            <span key={state}><i className={`coverage-${state}`} />{stateLabels[state]}</span>
          ))}
        </div>
        <div className="matrix-scroll" tabIndex={0}>
          <table className="coverage-matrix">
            <caption>Couverture des familles de données pour les neuf rencontres suivies</caption>
            <thead>
              <tr>
                <th scope="col">Rencontre</th>
                {matrixFamilies.map((family) => <th key={family} scope="col">{dataFamilyLabels[family]}</th>)}
              </tr>
            </thead>
            <tbody>
              {matches.map((match) => (
                <tr key={match.id}>
                  <th scope="row"><strong>{match.home}</strong><span>{match.away}</span></th>
                  {matrixFamilies.map((family) => {
                    const state = match.families[family];
                    return (
                      <td data-label={dataFamilyLabels[family]} key={family}>
                        <span className={`matrix-cell coverage-${state}`}>
                          <i aria-hidden="true" />
                          {stateLabels[state]}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <EvidenceNote>
          Une cellule « à venir » signifie que la fenêtre n’est pas encore due.
          Elle ne constitue ni une erreur ni une donnée absente.
        </EvidenceNote>
      </section>

      <section className="two-columns">
        <article className="section-card">
          <SectionHeading
            subtitle={t("observatory.gates.subtitle")}
            title={t("observatory.gates.title")}
          />
          <div className="gate-list">
            {gateRows.map((gate) => (
              <article key={gate.technicalName}>
                <div>
                  <h3>{gate.name}</h3>
                  <StatusBadge value={gate.status} />
                </div>
                <ProgressBar label={`${gate.passed} sur ${gate.total} vérifications`} value={gate.total ? gate.passed / gate.total : 0} />
                <p>{gate.reason}</p>
                <ExpertOnly><code>{gate.technicalName}</code></ExpertOnly>
              </article>
            ))}
          </div>
        </article>

        <div>
          <article className="section-card">
            <SectionHeading title={t("observatory.providers.title")} />
            <div className="provider-list">
              <div>
                <span className="provider-mark">AF</span>
                <div><strong>API-Football</strong><small>Aucun appel sur cette consultation</small></div>
                <StatusBadge value="READY" />
              </div>
              <div>
                <span className="provider-mark">O</span>
                <div><strong>The Odds API</strong><small>Aucun crédit consommé sur cette consultation</small></div>
                <StatusBadge value="READY" />
              </div>
            </div>
          </article>
          <article className="section-card">
            <SectionHeading title={t("observatory.storage.title")} />
            <div className="storage-bars">
              <ProgressBar label={`R2 · ${formatBytes(operationalEvidence.r2.bytes)}`} value={operationalEvidence.r2.objects / 100} />
              <ProgressBar label={`API-Football · 0 / ${formatNumber(operationalEvidence.providers.apiFootballCap)}`} value={0} />
              <ProgressBar label={`The Odds API · 0 / ${formatNumber(operationalEvidence.providers.oddsApiCap)} crédits`} value={0} />
            </div>
            <ExpertOnly>
              <TechnicalList rows={[
                { label: "Replay", value: <StatusBadge value={operationalEvidence.r2.replayStatus} showTechnical /> },
                { label: "Objets vérifiés", value: `${operationalEvidence.r2.verified} / ${operationalEvidence.r2.objects}` },
                { label: "Retard R2", value: `${operationalEvidence.r2.lag} objet` },
                { label: "Suppressions", value: operationalEvidence.r2.deletions },
              ]} />
            </ExpertOnly>
          </article>
        </div>
      </section>

      <ExpertOnly>
        <section className="section-card">
          <SectionHeading title="Couverture technique" subtitle="Détails réservés à la vue expert." />
          <TechnicalList rows={[
            { label: "Origine", value: <StatusBadge value={operationalEvidence.origin} showTechnical /> },
            { label: "Révision source", value: <code>{operationalEvidence.sourceRevision}</code> },
            { label: "Registre", value: `${formatNumber(operationalEvidence.ledger.events)} événements` },
            { label: "Couverture active", value: formatPercent(operationalEvidence.activeWindows / (operationalEvidence.activeWindows + operationalEvidence.inactiveLegacyWindows)) },
            { label: "Fenêtres legacy", value: `${formatNumber(operationalEvidence.inactiveLegacyWindows)} · replay uniquement` },
          ]} />
        </section>
      </ExpertOnly>
    </>
  );
}
