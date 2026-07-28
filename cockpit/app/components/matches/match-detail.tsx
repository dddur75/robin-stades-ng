"use client";

import Link from "next/link";
import { useState } from "react";

import {
  formatDateTime,
  formatPercent,
  t,
} from "../../i18n";
import {
  dataFamilyLabels,
  hypotheses,
  oddsSnapshots,
  operationalEvidence,
  type MatchPresentation,
} from "../../lib/presentation";
import {
  EmptyState,
  EvidenceNote,
  PageHeader,
  ProgressBar,
  StatusBadge,
  TechnicalList,
} from "../common/ui";
import { useViewMode } from "../common/view-mode";

type MatchTab =
  | "summary"
  | "odds"
  | "teams"
  | "players"
  | "absences"
  | "lineup"
  | "tactics"
  | "timeline"
  | "evidence";

const baseTabs: Array<{ key: MatchTab; label: ReturnType<typeof t> }> = [
  { key: "summary", label: t("match.tabs.summary") },
  { key: "odds", label: t("match.tabs.odds") },
  { key: "teams", label: t("match.tabs.teams") },
  { key: "players", label: t("match.tabs.players") },
  { key: "absences", label: t("match.tabs.absences") },
  { key: "lineup", label: t("match.tabs.lineup") },
  { key: "tactics", label: t("match.tabs.tactics") },
  { key: "timeline", label: t("match.tabs.timeline") },
];

export function MatchDetail({ match }: { match: MatchPresentation }) {
  const { isExpert } = useViewMode();
  const [tab, setTab] = useState<MatchTab>("summary");
  const tabs = isExpert
    ? [...baseTabs, { key: "evidence" as const, label: t("match.tabs.evidence") }]
    : baseTabs;
  const activeTab = !isExpert && tab === "evidence" ? "summary" : tab;

  const matchOdds = oddsSnapshots.filter(
    (snapshot) => snapshot.fixtureId === match.internalId,
  );

  return (
    <>
      <Link className="back-link" href="/matchs">← {t("action.backMatches")}</Link>
      <PageHeader
        eyebrow={`${t("match.eyebrow")} · ${match.competition}`}
        subtitle={formatDateTime(match.kickoff, true)}
        title={`${match.home} – ${match.away}`}
      >
        <StatusBadge value={match.dataStatus} showTechnical={isExpert} />
      </PageHeader>

      <nav className="tabs" aria-label="Rubriques de la rencontre">
        {tabs.map((item) => (
          <button
            aria-selected={activeTab === item.key}
            className={activeTab === item.key ? "active" : ""}
            key={item.key}
            onClick={() => setTab(item.key)}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="tab-panel" role="tabpanel">
        {activeTab === "summary" ? (
          <div className="match-summary-grid">
            <section className="feature-card score-card">
              <span className="competition-chip">{match.competition}</span>
              <div className="score-teams">
                <strong>{match.home}</strong>
                <span>VS</span>
                <strong>{match.away}</strong>
              </div>
              <time dateTime={match.kickoff}>{formatDateTime(match.kickoff, true)}</time>
              <StatusBadge value={match.matchStatus} showTechnical={isExpert} />
            </section>
            <section className="feature-card">
              <h2>{t("match.coverage")}</h2>
              <ProgressBar
                label={formatPercent(match.coverage)}
                value={match.coverage}
              />
              <div className="family-chips">
                {Object.entries(match.families).map(([family, state]) => (
                  <span className={`coverage-${state}`} key={family}>
                    <i aria-hidden="true" />
                    {dataFamilyLabels[family]}
                  </span>
                ))}
              </div>
            </section>
            <section className="feature-card">
              <h2>{t("match.expectedData")}</h2>
              {match.nextCapture && match.nextFamily ? (
                <>
                  <p>
                    <strong>{match.nextFamilies.map((family) => dataFamilyLabels[family] ?? family).join(" · ")}</strong>
                    <br />
                    {formatDateTime(match.nextCapture, true)}
                  </p>
                  <StatusBadge value="NOT_DUE" />
                </>
              ) : (
                <p>{t("common.notApplicable")}</p>
              )}
            </section>
            <section className="feature-card">
              <h2>Hypothèses concernées</h2>
              <ul className="compact-list">
                {hypotheses.slice(0, 4).map((hypothesis) => (
                  <li key={hypothesis.id}>{hypothesis.title}</li>
                ))}
              </ul>
            </section>
            <EvidenceNote>
              {t("home.understand.answer")}
            </EvidenceNote>
          </div>
        ) : null}

        {activeTab === "odds" ? (
          <section className="section-card">
            <h2>{t("match.oddsObserved")}</h2>
            {matchOdds.length ? (
              <div className="odds-grid">
                {matchOdds.map((snapshot) => (
                  <article key={snapshot.id}>
                    <div>
                      <strong>{formatDateTime(snapshot.observedAt, true)}</strong>
                      <span>{snapshot.bookmakers} bookmakers · {snapshot.quotes} prix</span>
                    </div>
                    <div className="probability-grid">
                      <span>Domicile <strong>{formatPercent(match.probabilities.home)}</strong></span>
                      <span>Nul <strong>{formatPercent(match.probabilities.draw)}</strong></span>
                      <span>Extérieur <strong>{formatPercent(match.probabilities.away)}</strong></span>
                    </div>
                    <small>Probabilités corrigées de la marge · marchés {snapshot.markets.join(" et ")}</small>
                    {isExpert ? <code>{snapshot.hash}</code> : null}
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState text={t("match.oddsNone.text")} title={t("match.oddsNone.title")} />
            )}
            <EvidenceNote>
              La source ne publie ici aucun prix individuel non présent dans le
              snapshot. Seuls les agrégats réellement capturés sont affichés.
            </EvidenceNote>
          </section>
        ) : null}

        {activeTab === "teams" ? (
          <section className="team-detail-grid">
            {[match.home, match.away].map((team, index) => (
              <article className="feature-card" key={team}>
                <span className="team-monogram" aria-hidden="true">{team.slice(0, 2).toUpperCase()}</span>
                <h2>{team}</h2>
                <p>Identité de l’équipe enregistrée pour cette rencontre.</p>
                <StatusBadge value="REGISTERED" />
                {isExpert ? <code>provider_team_position:{index === 0 ? "home" : "away"}</code> : null}
              </article>
            ))}
          </section>
        ) : null}

        {activeTab === "players" ? (
          <EmptyState text={t("match.playersNone.text")} title={t("match.playersNone.title")} />
        ) : null}
        {activeTab === "absences" ? (
          <EmptyState text={t("match.absenceNone.text")} title={t("match.absenceNone.title")} />
        ) : null}
        {activeTab === "lineup" ? (
          <EmptyState text={t("match.lineupNone.text")} title={t("match.lineupNone.title")} />
        ) : null}
        {activeTab === "tactics" ? (
          <EmptyState text={t("match.tacticsNone.text")} title={t("match.tacticsNone.title")} />
        ) : null}

        {activeTab === "timeline" ? (
          <section className="section-card">
            <h2>Chronologie pré-match</h2>
            {match.timeline.length ? (
              <ol className="capture-timeline">
                {match.timeline.map((window) => (
                  <li key={window.id}>
                    <span aria-hidden="true" />
                    <div>
                      <strong>{dataFamilyLabels[window.family] ?? window.family} · {window.label}</strong>
                      <time dateTime={window.dueAt}>{formatDateTime(window.dueAt, true)}</time>
                    </div>
                    <StatusBadge value={window.status} />
                  </li>
                ))}
                <li>
                  <span aria-hidden="true" />
                  <div>
                    <strong>Coup d’envoi</strong>
                    <time dateTime={match.kickoff}>{formatDateTime(match.kickoff, true)}</time>
                  </div>
                  <StatusBadge value="PENDING" />
                </li>
              </ol>
            ) : (
              <EmptyState
                title="Aucune fenêtre planifiée"
                text="Le snapshot ne contient aucune fenêtre active pour cette rencontre."
              />
            )}
          </section>
        ) : null}

        {activeTab === "evidence" && isExpert ? (
          <section className="section-card">
            <h2>{t("match.evidence.title")}</h2>
            <p>{t("match.evidence.subtitle")}</p>
            <TechnicalList
              rows={[
                { label: "Identifiant fournisseur", value: <code>{match.providerId}</code> },
                { label: "Identifiant interne", value: <code>{match.internalId}</code> },
                { label: "Équipe domicile", value: <code>{match.homeTeamId}</code> },
                { label: "Équipe extérieure", value: <code>{match.awayTeamId}</code> },
                { label: "Heure du coup d’envoi", value: <><span>{formatDateTime(match.kickoff, true)}</span><code>{match.kickoff}</code></> },
                { label: "Révision du code", value: <code>{operationalEvidence.sourceRevision}</code> },
                { label: "Origine", value: <><StatusBadge value={operationalEvidence.origin} showTechnical /></> },
                { label: "Heure limite", value: "Bornée par chaque fenêtre de capture" },
                { label: "Règle temporelle", value: <code>reçu avant cutoff, cutoff avant coup d’envoi</code> },
              ]}
            />
          </section>
        ) : null}
      </div>
    </>
  );
}
