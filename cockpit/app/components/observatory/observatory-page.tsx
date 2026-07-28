"use client";

import { useState } from "react";
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
  leagueSummaries,
  matches,
  nextCaptures,
  operationalEvidence,
  type CoverageState,
} from "../../lib/presentation";
import {
  EvidenceNote,
  EmptyState,
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
  const [selectedCompetition, setSelectedCompetition] = useState("Ligue 1");
  const providerErrorCount = leagueSummaries.filter(
    (league) => league.gate === "BLOCKED_PROVIDER_ERROR",
  ).length;
  const visibleMatches = selectedCompetition === "ALL"
    ? matches
    : matches.filter((match) => match.competition === selectedCompetition);
  const visibleFixtureIds = new Set(visibleMatches.map((match) => match.id));
  const visibleCaptures = selectedCompetition === "ALL"
    ? nextCaptures
    : nextCaptures.filter((capture) =>
        capture.fixtureIds.some((fixtureId) => visibleFixtureIds.has(fixtureId))
      );
  const selectedLeague = leagueSummaries.find(
    (league) => league.competition === selectedCompetition,
  );
  const selectedFixtures = selectedCompetition === "ALL"
    ? operationalEvidence.fixtures
    : selectedLeague?.fixtures ?? 0;
  const selectedWindows = selectedCompetition === "ALL"
    ? operationalEvidence.activeWindows
    : selectedLeague?.activeWindows ?? 0;
  const selectedDeep = selectedCompetition === "ALL"
    ? operationalEvidence.deepObservations
    : selectedLeague?.deepObservations ?? 0;
  return (
    <>
      <PageHeader
        eyebrow={t("observatory.eyebrow")}
        subtitle={t("observatory.subtitle")}
        title={t("observatory.title")}
      >
        <StatusBadge value={operationalEvidence.status} />
        <StatusBadge value={operationalEvidence.freshness.status} />
      </PageHeader>

      <section className="metrics-grid observatory-metrics" aria-label="Indicateurs de l’observatoire">
        <MetricCard detail="registre prospectif" icon="◉" label={t("observatory.metrics.fixtures")} tone="blue" value={formatNumber(selectedFixtures)} />
        <MetricCard detail="politique versionnée" icon="◫" label={t("observatory.metrics.activeWindows")} tone="green" value={formatNumber(selectedWindows)} />
        <MetricCard detail="à cet instant" icon="◷" label={t("observatory.metrics.dueWindows")} value={formatNumber(operationalEvidence.dueWindows)} />
        <MetricCard detail="vérifiées dans R2" icon="✓" label={t("observatory.metrics.physical")} tone="green" value={formatNumber(operationalEvidence.physicalEvidence)} />
        <MetricCard detail="collecte en attente" icon="◇" label={t("observatory.metrics.deep")} tone="violet" value={formatNumber(selectedDeep)} />
        <MetricCard
          detail={providerErrorCount ? "erreur fournisseur réelle" : "aucun incident actif"}
          icon="!"
          label={t("observatory.metrics.errors")}
          value={formatNumber(operationalEvidence.errors + providerErrorCount)}
        />
      </section>

      <section className="section-card">
        <SectionHeading
          title="Résumé par championnat"
          subtitle="La Ligue 1 reste sélectionnée par défaut ; « Tous » agrège les cinq ligues."
        />
        <div className="league-filter" aria-label="Filtrer par championnat">
          <button
            aria-pressed={selectedCompetition === "ALL"}
            onClick={() => setSelectedCompetition("ALL")}
            type="button"
          >
            Tous
          </button>
          {leagueSummaries.map((league) => (
            <button
              aria-pressed={selectedCompetition === league.competition}
              key={league.competition}
              onClick={() => setSelectedCompetition(league.competition)}
              type="button"
            >
              {league.competition}
            </button>
          ))}
        </div>
        <div className="league-summary-grid">
          {leagueSummaries.map((league) => (
            <article
              className={
                selectedCompetition === "ALL"
                || selectedCompetition === league.competition
                  ? "league-summary-card selected"
                  : "league-summary-card"
              }
              key={league.competition}
            >
              <div>
                <strong>{league.competition}</strong>
                <StatusBadge value={league.gate} />
              </div>
              <dl>
                <div><dt>Matchs</dt><dd>{formatNumber(league.fixtures)}</dd></div>
                <div><dt>Prochaines captures</dt><dd>{formatNumber(league.nextCaptures)}</dd></div>
                <div><dt>Couverture</dt><dd>{formatPercent(league.coverage)}</dd></div>
                <div><dt>Données profondes</dt><dd>{formatNumber(league.deepObservations)}</dd></div>
                <div><dt>API-Football</dt><dd>{formatNumber(league.apiFootballCalls)}</dd></div>
                <div><dt>Crédits Odds</dt><dd>{formatNumber(league.oddsApiCredits)}</dd></div>
              </dl>
              <ExpertOnly>
                <code>{league.captureProfile}</code>
              </ExpertOnly>
            </article>
          ))}
        </div>
      </section>

      <section className="section-card">
        <SectionHeading
          subtitle={t("observatory.timeline.subtitle")}
          title={t("observatory.timeline.title")}
        />
        {visibleCaptures.length ? <ol className="horizontal-timeline">
          {visibleCaptures.slice(0, 5).map((capture, index) => (
            <li key={capture.id}>
              <div>
                <span>{index + 1}</span>
                {index < 4 ? <i /> : null}
              </div>
              <time dateTime={capture.dueAt}>{formatDateTime(capture.dueAt, true)}</time>
              <strong>{capture.match}</strong>
              <small>{capture.families.map((family) => dataFamilyLabels[family] ?? family).join(" · ")}</small>
              <StatusBadge value={capture.status} />
            </li>
          ))}
        </ol> : (
          <EmptyState
            title="Aucune fenêtre à venir"
            text="Le snapshot ne contient aucune fenêtre active à afficher."
          />
        )}
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
        {visibleMatches.length ? <div className="matrix-scroll" tabIndex={0}>
          <table className="coverage-matrix">
            <caption>Couverture des familles de données pour {formatNumber(visibleMatches.length)} rencontre{visibleMatches.length > 1 ? "s" : ""} suivie{visibleMatches.length > 1 ? "s" : ""}</caption>
            <thead>
              <tr>
                <th scope="col">Rencontre</th>
                {matrixFamilies.map((family) => <th key={family} scope="col">{dataFamilyLabels[family]}</th>)}
              </tr>
            </thead>
            <tbody>
              {visibleMatches.map((match) => (
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
        </div> : (
          <EmptyState
            title="Aucune rencontre suivie"
            text="La matrice se remplira automatiquement lorsque le registre prospectif contiendra une fixture active."
          />
        )}
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
              <ProgressBar label={`R2 · ${formatBytes(operationalEvidence.r2.bytes)}`} value={operationalEvidence.r2.objects ? operationalEvidence.r2.verified / operationalEvidence.r2.objects : 0} />
              <ProgressBar label={`API-Football · ${formatNumber(operationalEvidence.providers.apiFootballCalls)} / ${formatNumber(operationalEvidence.providers.apiFootballCap)}`} value={operationalEvidence.providers.apiFootballCap ? operationalEvidence.providers.apiFootballCalls / operationalEvidence.providers.apiFootballCap : 0} />
              <ProgressBar label={`The Odds API · ${formatNumber(operationalEvidence.providers.oddsApiCredits)} / ${formatNumber(operationalEvidence.providers.oddsApiCap)} crédits`} value={operationalEvidence.providers.oddsApiCap ? operationalEvidence.providers.oddsApiCredits / operationalEvidence.providers.oddsApiCap : 0} />
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
            { label: "Couverture active", value: formatPercent(
              operationalEvidence.activeWindows + operationalEvidence.inactiveLegacyWindows
                ? operationalEvidence.activeWindows / (operationalEvidence.activeWindows + operationalEvidence.inactiveLegacyWindows)
                : null,
            ) },
            { label: "Fenêtres legacy", value: `${formatNumber(operationalEvidence.inactiveLegacyWindows)} · replay uniquement` },
            { label: "Fraîcheur", value: <StatusBadge value={operationalEvidence.freshness.status} showTechnical /> },
            { label: "Motif fraîcheur", value: operationalEvidence.freshness.reason },
          ]} />
        </section>
      </ExpertOnly>
    </>
  );
}
