"use client";

import { useState } from "react";

import { formatDateTime, formatNumber, formatPercent, t } from "../../i18n";
import { EmptyState, EvidenceNote, MetricCard, PageHeader, SectionHeading } from "../common/ui";

type SourceAccess = "a_construire" | "manuel";

type VisitCounts = {
  succeeded: number;
  failed: number;
  blockedRobots: number;
  withoutReceipt: number;
};

export type SourceObservatorySnapshot = {
  plan: {
    claimId: string;
    startsAt: string;
    lastVisitAt: string;
    fixtureCount: number;
    plannedVisits: number;
  };
  sources: {
    id: string;
    name: string;
    audience: string;
    access: SourceAccess;
    plannedVisits: number;
  }[];
  observations: {
    claimId: string;
    totals: VisitCounts;
    bySource: Record<string, VisitCounts>;
    publications: number;
  } | null;
};

const accessLabels: Record<SourceAccess, string> = {
  a_construire: "À vérifier avant collecte",
  manuel: "Accès manuel",
};

function searchText(value: string) {
  return value.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
}

export function SourceObservatory({ snapshot }: { snapshot: SourceObservatorySnapshot }) {
  const [query, setQuery] = useState("");
  const [access, setAccess] = useState("");
  const { plan, observations, sources } = snapshot;
  const selection = sources.filter((source) =>
    (!access || source.access === access)
    && searchText(`${source.id} ${source.name}`).includes(searchText(query)),
  );

  return (
    <>
      <PageHeader
        eyebrow="Dossier fidèle · Ligue 1"
        title={t("nav.expert.sourceObservatory")}
        subtitle="Consultez les sources de pronostics des tipsters et les visites documentées du pilote."
      />
      <section className="section-card" aria-label="Plan du pilote">
        <SectionHeading
          title="Plan historique du pilote"
          subtitle={`Du ${formatDateTime(plan.startsAt, true)} au ${formatDateTime(plan.lastVisitAt, true)} · Heure de Paris`}
        />
        <div className="metrics-grid source-observatory-metrics">
          <MetricCard label="Sources inscrites au plan" value={formatNumber(sources.length)}
            detail="Périmètre prévu" />
          <MetricCard label="Matchs retenus" value={formatNumber(plan.fixtureCount)}
            detail="Ligue 1" />
          <MetricCard label="Visites planifiées" value={formatNumber(plan.plannedVisits)}
            detail="Sources manuelles incluses" />
        </div>
        <details>
          <summary>Référence du plan</summary>
          <p>{plan.claimId}</p>
        </details>
      </section>
      <section className="section-card" aria-label="Résultats de la collecte">
        <SectionHeading title="Résultats de la collecte" />
        {observations ? (
          <>
            <div className="metrics-grid source-observatory-metrics">
              <MetricCard label="Visites réussies" value={formatNumber(observations.totals.succeeded)}
                detail={`${formatPercent(observations.totals.succeeded / plan.plannedVisits)} des visites planifiées`} />
              <MetricCard label="Visites en échec" value={formatNumber(observations.totals.failed)}
                detail="Échec documenté" />
              <MetricCard label="Blocages robots.txt" value={formatNumber(observations.totals.blockedRobots)}
                detail="Accès automatisé refusé" />
              <MetricCard label="Visites sans reçu" value={formatNumber(observations.totals.withoutReceipt)}
                detail="Incluses dans le plan" />
              <MetricCard label="Publications observées" value={formatNumber(observations.publications)}
                detail="Publications distinctes rattachées aux visites réussies" />
            </div>
            <details>
              <summary>Référence du journal</summary>
              <p>{observations.claimId}</p>
            </details>
          </>
        ) : (
          <EmptyState
            title="Journal du pilote indisponible"
            text="Les résultats resteront indisponibles tant que le journal de collecte et sa preuve d’intégrité ne sont pas retrouvés."
          />
        )}
      </section>
      <section className="section-card" aria-label="Sources du plan">
        <SectionHeading
          title="Sources du plan"
          subtitle="L’état d’accès a été relevé pendant la préparation du pilote."
        />
        <div className="filter-panel source-observatory-filter">
          <label>
            <span>Rechercher une source</span>
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <label>
            <span>État d’accès</span>
            <select value={access} onChange={(event) => setAccess(event.target.value)}>
              <option value="">Tous les états</option>
              {Object.entries(accessLabels).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>
        <p role="status">
          {formatNumber(selection.length)} {selection.length === 1 ? "source affichée" : "sources affichées"}
        </p>
        {selection.length === 0 ? (
          <EmptyState title="Aucune source correspondante" text="Essayez un autre nom ou identifiant." />
        ) : (
          <div className="table-scroll" role="region" aria-label="Tableau des sources du pilote" tabIndex={0}>
            <table>
              <caption>Sources du pilote et état de leurs visites</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">État d’accès</th>
                  <th scope="col">Visites prévues</th>
                  {observations && <th scope="col">Visites réussies</th>}
                </tr>
              </thead>
              <tbody>
                {selection.map((source) => (
                  <tr key={source.id}>
                    <th scope="row">
                      <strong>{source.name}</strong><br />
                      <small>{source.id}{source.audience === "petit_auteur_inconnu" ? " · Petit auteur" : ""}</small>
                    </th>
                    <td>{accessLabels[source.access]}</td>
                    <td>{formatNumber(source.plannedVisits)}</td>
                    {observations && <td>{formatNumber(observations.bySource[source.id].succeeded)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <EvidenceNote>
          Un créneau prévu ne prouve pas une visite. Les auteurs restent en observation pendant le pilote.
        </EvidenceNote>
      </section>
    </>
  );
}
