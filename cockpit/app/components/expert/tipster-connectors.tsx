"use client";

import { useEffect, useState } from "react";
import { formatDateTime } from "../../i18n";
import { marketLabels, selectionLabels } from "../../lib/tipsters-pilot";
import { InlineLink, MetricCard, SectionHeading } from "../common/ui";

type Candidate = { id: string; authorId: string; sourceId: string; market: string; selection: string;
  line: string | null; extractionStatus: string; declaredOdds: string | null; url: string; observedAt: string };
type Profile = { id: string; name: string; endpoint: string; adapter: string };
type Publication = { id: string; sourceId: string; authorId: string | null; contentSha256: string;
  url: string; announcedAt: string | null; observedAt: string };
type SourceResult = { sourceId: string; status: string; publications: unknown[]; candidates: Candidate[]; at: string };
type View = { status: string; running: boolean; canRun: boolean; updatedAt: string | null; journalHead: string;
  launchBlockReason?: string | null;
  mission: { expires_at: string } | null; profiles: Profile[]; sources: SourceResult[];
  counts: { requests: number; attemptedSources: number; collectedSources: number; publications: number;
    candidates: number; unresolvedExtractions?: number; verifiedPreMatch: number }; candidates: Candidate[];
  publications?: Publication[] };

const labels: Record<string, string> = {
  collected: "Publications collectées", readable_no_publication: "Lecture réussie, aucun élément",
  permission_required: "Permission de l’éditeur requise", terms_unverified: "Conditions non vérifiées",
  robots_denied: "Lecture refusée par robots.txt", read_failed: "Lecture échouée, aucun nouvel essai",
  official_api_required: "Interface officielle à autoriser", cross_domain_permission_required: "Domaine tiers à valider",
  interrupted_no_retry: "Interrompue, aucun nouvel essai", crawl_delay_exceeds_budget: "Délai supérieur au budget",
};
function stateLabel(value?: string): string {
  if (!value) return "À vérifier";
  return labels[value] ?? value.replace("robots_http_", "Robots, HTTP ").replace("terms_http_", "Conditions, HTTP ")
    .replace("content_http_", "Contenu, HTTP ");
}

export function TipsterConnectors({ compact = false, authorId }: { compact?: boolean; authorId?: string }) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [query, setQuery] = useState("");
  useEffect(() => {
    let alive = true;
    let reading = false;
    async function refresh() {
      if (reading) return;
      reading = true;
      try {
        const response = await fetch("/api/tipsters/connectors", { cache: "no-store", signal: AbortSignal.timeout(10_000) });
        const result = await response.json();
        if (!response.ok || result.status !== "ok") throw new Error(result.message || "Collecte indisponible.");
        if (alive) { setView(result); setError(""); }
      } catch { if (alive) setError("La collecte locale est indisponible. La dernière vue conserve sa date."); }
      finally { reading = false; }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 5_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  async function run() {
    setPending(true);
    setNotice("");
    try {
      const response = await fetch("/api/tipsters/connectors", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sourceId: "all" }),
        signal: AbortSignal.timeout(10_000) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message);
      setNotice(result.message);
    } catch { setNotice("Le lancement n’a pas été confirmé. Vérifiez le suivi avant de recommencer."); }
    finally { setPending(false); }
  }
  function download() {
    if (!view || error) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(view, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "robin-collecte-sources.json";
    anchor.click(); URL.revokeObjectURL(url);
  }
  const counts = view?.counts;
  const remaining = view ? view.profiles.length - view.counts.attemptedSources : 0;
  const expired = !view?.canRun;
  const attributed = view?.publications?.filter((p) => p.authorId) ?? [];
  const authors = [...new Set(attributed.map((p) => p.authorId!))];
  const authorPublications = attributed.filter((p) => p.authorId === authorId);
  if (authorId) return <section className="section-card">
    <InlineLink href="/expert/tipsters">Retour aux tipsters et attributions</InlineLink>
    <h2>Attribution {authorId.slice(7, 19)}</h2>
    <p>Identité humaine non vérifiée. Le flux déclare cette attribution, conservée sous un pseudonyme propre à la source.</p>
    {view?.updatedAt && <p>Dernière preuve : {formatDateTime(view.updatedAt, true)}.</p>}
    {error && <p role="alert">{error}</p>}
    {!view ? <p role="status">{error ? "La fiche est indisponible sur cette connexion." : "Lecture des publications…"}</p> : authorPublications.length === 0
      ? <p>Aucune publication vérifiée dans ce journal ne correspond à cette attribution.</p> : <>
        <p>{authorPublications.length} version(s) de publication observée(s). Aucun pronostic vérifié avant match pour cette attribution.</p>
        <ul>{authorPublications.slice(0, 100).map((p) => <li key={`${p.id}-${p.contentSha256}`}>
          <a href={p.url} target="_blank" rel="noreferrer">Publication {p.sourceId}</a>
          {" · "}Publication déclarée : {p.announcedAt ? formatDateTime(p.announcedAt, true) : "date absente"}.
          {" "}Lue le {formatDateTime(p.observedAt, true)}.
        </li>)}</ul>
        <p>Aucun score de performance n’est calculé à partir de ces publications.</p>
      </>}
  </section>;
  return <section className="section-card" aria-labelledby={compact ? "connector-summary" : "connector-admin"}>
    <h2 id={compact ? "connector-summary" : "connector-admin"}>Collecte des sources tipsters</h2>
    <p>Le suivi sépare les publications lues, les sélections à vérifier et les pronostics prouvés avant match.</p>
    {error && <p role="alert">{error}</p>}
    {!view && !error && <p role="status">Lecture des reçus locaux…</p>}
    {view && <>
      <p>Dernière preuve : {view.updatedAt ? formatDateTime(view.updatedAt) : "Aucune lecture"}.
        {view.running ? " Collecte en cours." : " Aucune exécution en cours."}</p>
      <div className="metrics-grid source-observatory-metrics">
        <MetricCard label="Sources avec publications" value={String(counts?.collectedSources ?? 0)} detail={`${counts?.attemptedSources ?? 0} profils traités sur 57`} />
        <MetricCard label="Publications distinctes" value={String(counts?.publications ?? 0)} detail="Liens, dates, empreintes et attribution disponible" />
        <MetricCard label="Sélections à vérifier" value={String(counts?.candidates ?? 0)} detail="Match et identité humaine à confirmer" />
        <MetricCard label="Pronostics vérifiés avant match" value={String(counts?.verifiedPreMatch ?? 0)} detail="Les candidats ne sont pas comptés ici" />
      </div>
      {compact ? <InlineLink href="/expert/admin-collecte">Ouvrir le suivi des 57 connecteurs</InlineLink> : <>
        <p>{counts?.requests ?? 0} requêtes réservées sur 228 maximum. Quatre au plus par source. Expiration : {view.mission ? formatDateTime(view.mission.expires_at) : "Mission absente"}.</p>
        {expired && <p>{view.launchBlockReason ?? "Mission expirée ou absente. Un nouveau plan est requis."}</p>}
        <div className="pilot-actions">
          <button className="pilot-button" type="button" onClick={() => void run()} disabled={pending || view.running || expired || remaining === 0 || !!error}>
            {pending ? "Demande en cours…" : remaining === 0 ? "Qualification terminée" : `Vérifier les ${remaining} sources restantes`}</button>
          <button className="pilot-button" type="button" onClick={download} disabled={!!error}>Exporter les reçus structurés</button>
        </div>
        <p role="status">{notice}</p>
        <label>Rechercher un connecteur <input value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="table-scroll" role="region" aria-label="Résultats des connecteurs" tabIndex={0} style={{ maxHeight: 600, overflow: "auto" }}>
          <table><caption>État réel de chaque source</caption><thead><tr><th scope="col">Source</th><th scope="col">Résultat</th><th scope="col">Publications</th><th scope="col">Sélections à vérifier</th></tr></thead>
            <tbody>{view.profiles.filter((p) => `${p.id} ${p.name}`.toLowerCase().includes(query.toLowerCase())).map((profile) => {
              const result = view.sources.find((r) => r.sourceId === profile.id);
              return <tr key={profile.id}><th scope="row"><a href={profile.endpoint} target="_blank" rel="noreferrer">{profile.name}</a><small>{profile.id}</small></th>
                <td>{stateLabel(result?.status)}</td><td>{result?.publications.length ?? 0}</td><td>{result?.candidates.length ?? 0}</td></tr>;
            })}</tbody></table>
        </div>
        {view.profiles.every((p) => !`${p.id} ${p.name}`.toLowerCase().includes(query.toLowerCase())) && <p role="status">Aucun connecteur ne correspond à cette recherche.</p>}
        <p>Les sources traitées ne sont pas rejouées. Un nouveau plan est nécessaire pour renouveler la collecte ou adopter un réglage modifié. Le pilote Forecast Record conserve son budget distinct de 51 requêtes.</p>
      </>}
      <SectionHeading title="Sélections collectées à rapprocher" subtitle="L’auteur est attribué par le flux, son identité humaine reste à vérifier. Aucun résultat sportif n’est déduit." />
      <p>{counts?.unresolvedExtractions ?? 0} extraction(s) ambiguë(s) exclue(s) du compteur des sélections.</p>
      {view.candidates.length === 0 ? <p>Aucune sélection explicitement attribuée n’a été extraite des lectures autorisées.</p>
        : <><p>{Math.min(view.candidates.length, compact ? 5 : 50)} sélection(s) affichée(s) sur {view.candidates.length}.</p><ul>{view.candidates.slice(0, compact ? 5 : 50).map((pick) => <li key={pick.id}>
          <a href={pick.url} target="_blank" rel="noreferrer">{pick.sourceId} · Auteur {pick.authorId.slice(7, 19)}</a>
          {" — "}{marketLabels[pick.market.toLowerCase()] ?? ({ "1n2": "Résultat du match", btts: "Les deux équipes marquent", double_chance: "Double chance", combine: "Combiné" } as Record<string, string>)[pick.market.toLowerCase()] ?? pick.market} : {selectionLabels[pick.selection] ?? pick.selection}{pick.line ? ` ${pick.line}` : ""}. Cote déclarée : {pick.declaredOdds ?? "absente"}.
          {pick.extractionStatus !== "resolu" && " Extraction ambiguë à examiner."}
          Observé le {formatDateTime(pick.observedAt)}. Match non rapproché.
        </li>)}</ul></>}
      <SectionHeading title="Attributions à vérifier" subtitle="Ces fiches proviennent des métadonnées déclarées par les sources. Elles ne prouvent pas qu’un tipster humain a publié un pronostic." />
      <p>{authors.length} attribution(s) avec publication. {Math.min(authors.length, compact ? 10 : 50)} fiche(s) affichée(s).</p>
      {authors.length ? <ul>{authors.slice(0, compact ? 10 : 50).map((id) => <li key={id}>
        <InlineLink href={`/expert/tipsters/${encodeURIComponent(id)}`}>Attribution {id.slice(7, 19)}</InlineLink>
        {" · "}{attributed.filter((p) => p.authorId === id).length} version(s) de publication · Identité humaine non vérifiée
      </li>)}</ul> : <p>Aucune attribution explicite disponible.</p>}
      <details><summary>Preuve de la vue</summary><p>ENG.SOURCE_OBSERVATORY.CONNECTORS57.20261118</p><code style={{ overflowWrap: "anywhere" }}>{view.journalHead}</code></details>
    </>}
  </section>;
}
