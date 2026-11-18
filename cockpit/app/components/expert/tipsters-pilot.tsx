"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { formatDateTime, formatNumber } from "../../i18n";
import { marketLabels, periodLabels, selectionLabels, visitLabels, type PilotPick, type PilotSnapshot } from "../../lib/tipsters-pilot";
import { EmptyState, EvidenceNote, InlineLink, MetricCard, PageHeader, SectionHeading } from "../common/ui";

function usePilot() {
  const [snapshot, setSnapshot] = useState<PilotSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(() => {
    if (controller.current) return;
    const request = new AbortController();
    controller.current = request;
    const timeout = window.setTimeout(() => request.abort(), 12_000);
    return fetch("/api/tipsters", { cache: "no-store", signal: request.signal }).then(async (response) => {
      if (!response.headers.get("content-type")?.includes("application/json")) {
        throw new Error("Ouvrez cette page dans Robin sur A9_Mega pour consulter le pilote local.");
      }
      const value = await response.json();
      if (!response.ok || value.status !== "ok" || value.schemaVersion !== "robin-tipsters-pilot-v1") {
        throw new Error(value.message || "Le suivi local est temporairement indisponible.");
      }
      return value as PilotSnapshot;
    }).then((value) => {
      if (request.signal.aborted) return;
      setSnapshot(value);
      setError(null);
    }).catch((reason: unknown) => {
      if (controller.current !== request) return;
      setError(reason instanceof Error && reason.name !== "AbortError"
        ? reason.message : "La lecture du suivi a dépassé le délai prévu.");
    }).finally(() => {
      clearTimeout(timeout);
      if (controller.current !== request) return;
      controller.current = null;
      setLoading(false);
    });
  }, []);
  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => { if (!document.hidden) void refresh(); }, 30_000);
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", focus);
      controller.current?.abort();
      controller.current = null;
    };
  }, [refresh]);
  const reload = () => { setLoading(true); void refresh(); };
  return { snapshot, error, loading, refresh: reload };
}

function stamp(value: string | null) {
  return value ? `${formatDateTime(value, true)} · Paris` : "Absente";
}

function exportSnapshot(snapshot: PilotSnapshot) {
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `robin-tipsters-${snapshot.missionId}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

function PickCard({ pick, snapshot }: { pick: PilotPick; snapshot: PilotSnapshot }) {
  const fixture = snapshot.fixtures.find((item) => item.id === pick.fixtureId)!;
  const version = pick.versions[0];
  return (
    <article className="section-card tipster-pick">
      <h3>{fixture.label}</h3>
      <p><small>Première version observée</small></p>
      <p>{marketLabels[version.market] ?? version.market} · {selectionLabels[version.selection] ?? version.selection}
        {version.line !== null ? ` ${version.line}` : ""}</p>
      <dl className="pilot-facts">
        <div><dt>Cote déclarée</dt><dd>{version.odds ?? "Absente"}</dd></div>
        <div><dt>Période</dt><dd>{version.period ? periodLabels[version.period] ?? version.period : "Non précisée"}</dd></div>
        <div><dt>Coup d’envoi</dt><dd>{stamp(fixture.kickoff)}</dd></div>
        <div><dt>Première lecture avant match</dt><dd>{stamp(pick.firstSeenAt)}</dd></div>
        <div><dt>Détection par Forecast Record</dt><dd>{stamp(version.detectedAt)}</dd></div>
        <div><dt>Publication déclarée</dt><dd>{stamp(version.publishedAt)}</dd></div>
      </dl>
      <a className="inline-link" href={version.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter la source</a>
      <p><small>En observation · {pick.versions.length} version{pick.versions.length > 1 ? "s" : ""} observée{pick.versions.length > 1 ? "s" : ""}</small></p>
      {pick.versions.length > 1 && <details>
        <summary>Historique du pronostic</summary>
        <ol>{pick.versions.map((item, index) => <li key={index}>
          {stamp(item.observedAt)} · {marketLabels[item.market] ?? item.market} · {selectionLabels[item.selection] ?? item.selection}
          {item.line !== null ? ` ${item.line}` : ""} · Cote {item.odds ?? "absente"}
        </li>)}</ol>
      </details>}
    </article>
  );
}

function TipsterDirectory({ snapshot, tipsterId }: { snapshot: PilotSnapshot; tipsterId?: string }) {
  const [query, setQuery] = useState("");
  const [fixtureId, setFixtureId] = useState("");
  if (tipsterId) {
    const author = snapshot.tipsters.find((item) => item.id === tipsterId);
    return <>
      <p><InlineLink href="/expert/tipsters">Tous les tipsters</InlineLink></p>
      {author ? <>
        <SectionHeading title={author.label} subtitle="En observation · Pseudonyme technique d’attribution par source" />
        <p>{author.picks} pronostic{author.picks > 1 ? "s" : ""} distinct{author.picks > 1 ? "s" : ""} sur {author.fixtureIds.length} rencontre{author.fixtureIds.length > 1 ? "s" : ""}.</p>
        {author.attributionBasis === "publication" && <EvidenceNote>L’attribution de ce journal est limitée à la publication d’origine.</EvidenceNote>}
        {snapshot.picks.filter((pick) => pick.authorId === tipsterId).map((pick) => <PickCard key={pick.id} pick={pick} snapshot={snapshot} />)}
      </> : <EmptyState title="Fiche tipster indisponible" text="Aucun pronostic vérifié ne correspond à cette fiche dans le journal actuel." />}
    </>;
  }
  const authors = snapshot.tipsters.filter((author) => author.label.toLowerCase().includes(query.toLowerCase().trim())
    && (!fixtureId || author.fixtureIds.includes(fixtureId)));
  return <section className="section-card">
    <SectionHeading title="Tipsters en observation" />
    <div className="filter-panel pilot-filters">
      <label><span>Rechercher un tipster</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <label><span>Rencontre</span><select value={fixtureId} onChange={(event) => setFixtureId(event.target.value)}>
        <option value="">Toutes les rencontres</option>
        {snapshot.fixtures.map((fixture) => <option key={fixture.id} value={fixture.id}>{fixture.label}</option>)}
      </select></label>
    </div>
    <p role="status">{authors.length} fiche{authors.length > 1 ? "s" : ""} affichée{authors.length > 1 ? "s" : ""}</p>
    {authors.length ? <div className="pilot-author-grid">{authors.map((author) => <article key={author.id} className="tipster-summary">
      <h3><Link className="inline-link" href={`/expert/tipsters/${author.id}`}>{author.label}</Link></h3>
      <p>{author.picks} pronostic{author.picks > 1 ? "s" : ""} · {author.fixtureIds.length} rencontre{author.fixtureIds.length > 1 ? "s" : ""}</p>
      <small>Première lecture {stamp(author.firstSeenAt)}</small>
    </article>)}</div> : <EmptyState
      title={snapshot.tipsters.length ? "Aucun tipster correspondant" : "En attente de pronostics vérifiés"}
      text="Les fiches se créent à partir des pronostics attribués et horodatés disponibles dans le journal." />}
    <EvidenceNote>Les fiches utilisent les attributions pseudonymisées du fournisseur. Les pronostics restent en observation.</EvidenceNote>
  </section>;
}

function CollectionAdmin({ snapshot }: { snapshot: PilotSnapshot }) {
  const [state, setState] = useState("");
  const selection = snapshot.visits.filter((visit) => !state || visit.status === state);
  return <>
    <section className="section-card">
      <SectionHeading title="État du pilote" subtitle={`${stamp(snapshot.startsAt)} au ${stamp(snapshot.expiresAt)}`} />
      <p>{({ scheduled: "Collecte programmée", collecting: "Fenêtre de collecte ouverte", closed: "Fenêtre de collecte close" })[snapshot.phase]}</p>
      <div className="metrics-grid source-observatory-metrics">
        <MetricCard label="Visites réussies" value={snapshot.journalHead ? formatNumber(snapshot.counts.succeeded ?? 0) : "En attente"} detail={`Sur ${snapshot.plannedVisits} visites de match prévues`} />
        <MetricCard label="Échecs de lecture" value={snapshot.journalHead ? formatNumber(snapshot.counts.failed ?? 0) : "En attente"} detail="Visites avec échec documenté" />
        <MetricCard label="Blocages robots.txt" value={snapshot.journalHead ? formatNumber(snapshot.counts.blocked ?? 0) : "En attente"} detail="Visites bloquées dans le journal" />
        <MetricCard label="Créneaux manqués" value={formatNumber(snapshot.counts.missed ?? 0)} detail="Visites échues sans reçu" />
        <MetricCard label="Interrompues" value={formatNumber(snapshot.counts.interrupted ?? 0)} detail="Visites commencées sans reçu après quatre minutes" />
        <MetricCard label="Plafond de requêtes" value={formatNumber(snapshot.requestsMax)} detail={`${snapshot.plannedSlots} vérifications robots.txt et ${snapshot.plannedVisits} lectures de match`} />
      </div>
      <p>Dernière lecture de match {snapshot.lastObservationAt ? stamp(snapshot.lastObservationAt) : "encore absente"}.</p>
      <p>Recette technique {snapshot.technicalVerdict === "PENDING" ? "en attente de clôture" : snapshot.technicalVerdict === "PASS_AND_HOLD" ? "réussie sur le périmètre du pilote" : "partielle"}. Dossier fidèle en recette partielle.</p>
      <details><summary>Preuve du suivi</summary><p><code>{snapshot.evidence.claimId}</code></p><p>Empreinte du plan <code>{snapshot.evidence.planSha256}</code></p><p>Tête du journal <code>{snapshot.journalHead ?? "Journal encore absent"}</code></p></details>
    </section>
    <section className="section-card">
      <SectionHeading title="Journal des visites" />
      <label className="pilot-state-filter"><span>État des visites</span><select value={state} onChange={(event) => setState(event.target.value)}>
        <option value="">Tous les états</option>{Object.entries(visitLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
      <p role="status">{selection.length} visite{selection.length > 1 ? "s" : ""} affichée{selection.length > 1 ? "s" : ""}</p>
      {selection.length ? <div className="table-scroll" role="region" aria-label="Visites du pilote" tabIndex={0}><table>
        <caption>Créneaux et lectures du pilote Forecast Record</caption>
        <thead><tr><th scope="col">Créneau, heure de Paris</th><th scope="col">Rencontre</th><th scope="col">État</th><th scope="col">Pronostics dans la visite</th></tr></thead>
        <tbody>{selection.map((visit) => <tr key={`${visit.slot}-${visit.fixtureId}`}>
          <td>{formatDateTime(visit.slot, true)}</td><td>{snapshot.fixtures.find((f) => f.id === visit.fixtureId)?.label}</td>
          <td>{visitLabels[visit.status]}</td><td>{visit.picks ?? "En attente"}</td>
        </tr>)}</tbody>
      </table></div> : <EmptyState title="Aucune visite dans cet état" text="Sélectionnez un autre état pour consulter les créneaux du plan." />}
    </section>
  </>;
}

export function TipstersPilot({ admin = false, tipsterId }: { admin?: boolean; tipsterId?: string }) {
  const { snapshot, error, loading, refresh } = usePilot();
  return <>
    <PageHeader eyebrow="Dossier fidèle · Ligue 1" title={admin ? "Suivi admin de la collecte" : "Tipsters et pronostics"}
      subtitle={admin ? "Suivez les créneaux et les preuves du pilote local sur A9_Mega." : "Consultez les pronostics attribués aux tipsters et lus avant les matchs."} />
    <nav className="pilot-actions" aria-label="Suivi des tipsters">
      <InlineLink href="/expert/sources-tipsters">Paramétrage des sources</InlineLink>
      <InlineLink href={admin ? "/expert/tipsters" : "/expert/admin-collecte"}>{admin ? "Fiches tipsters" : "Suivi admin"}</InlineLink>
      <button type="button" className="pilot-button" onClick={() => void refresh()} disabled={loading}>{loading ? "Lecture en cours…" : "Actualiser le suivi"}</button>
      {snapshot && <button type="button" className="pilot-button" onClick={() => exportSnapshot(snapshot)} disabled={Boolean(error) || loading}>Télécharger le bilan JSON</button>}
    </nav>
    <p className="pilot-refresh" role="status" aria-live="polite">{snapshot ? `Suivi vérifié le ${stamp(snapshot.generatedAt)}. Actualisation toutes les 30 secondes.` : loading ? "Lecture du journal local…" : "Le suivi local est indisponible."}</p>
    {error && <div role="alert" className="pilot-alert"><p>{error}</p>{snapshot && <p>Dernier suivi vérifié conservé du {stamp(snapshot.generatedAt)}.</p>}</div>}
    {snapshot ? <>
      {!admin && <div className="metrics-grid source-observatory-metrics">
        <MetricCard label="Pronostics distincts avant match" value={snapshot.distinctPicks === null ? "En attente" : formatNumber(snapshot.distinctPicks)} detail="Dédupliqués par rencontre et identifiant fournisseur" />
        <MetricCard label="Tipsters observés" value={snapshot.distinctPicks === null ? "En attente" : formatNumber(snapshot.tipsters.length)} detail="Attributions pseudonymisées par source" />
        <MetricCard label="Rencontres du pilote" value={formatNumber(snapshot.fixtures.length)} detail={snapshot.source} />
      </div>}
      {admin ? <CollectionAdmin snapshot={snapshot} /> : <TipsterDirectory snapshot={snapshot} tipsterId={tipsterId} />}
      <p className="pilot-credit">Provenance des mesures et attributions · Forecast Record</p>
    </> : !loading && <EmptyState title="Connexion au pilote local requise" text="Les preuves du pilote sont conservées sur A9_Mega. Le suivi devient disponible dans Robin lancé sur ce poste." />}
  </>;
}
