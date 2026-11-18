"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { formatDateTime, formatNumber } from "../../i18n";
import { EmptyState, EvidenceNote, InlineLink, MetricCard, PageHeader, SectionHeading } from "../common/ui";

type Config = {
  endpoint: string;
  adapter: "rss_atom" | "html_public" | "manual";
  intervalMinutes: number;
  requestsPerVisit: number;
  notes: string;
};

type Source = {
  id: string;
  name: string;
  url: string;
  historicalState: "a_construire" | "manuel" | "bloque";
  historicalCheckedAt: string;
  historicalAccess: string;
  historicalTerms: string;
  limits: string;
  competitions: string;
  historicalGate: string;
  prepared: boolean;
  savedAt: string | null;
  config: Config;
};

export type SourceCatalogue = {
  status: "ok";
  schemaVersion: "robin-tipsters-source-settings-v1";
  revision: string;
  registrySha256: string;
  total: number;
  prepared: number;
  counts: Record<string, number>;
  sources: Source[];
  pilotProvider: { id: string; name: string; requestsMax: number; detailsHref: string };
};

type Draft = { config: Config; revision: string };
const stateLabels = { a_construire: "À construire", manuel: "Manuelle", bloque: "Bloquée" };
const adapterLabels = { rss_atom: "Flux RSS / Atom", html_public: "Page HTML publique", manual: "Lecture manuelle" };

async function readCatalogue(signal?: AbortSignal): Promise<SourceCatalogue> {
  const response = await fetch("/api/tipsters/sources", { cache: "no-store", signal: signal ?? AbortSignal.timeout(12_000) });
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("Ouvrez Robin sur A9_Mega pour paramétrer les sources locales.");
  }
  const data = await response.json();
  if (!response.ok || data.status !== "ok" || data.schemaVersion !== "robin-tipsters-source-settings-v1") {
    throw new Error(data.message || "Le registre des sources est indisponible.");
  }
  return data as SourceCatalogue;
}

export function TipsterSources() {
  const [catalogue, setCatalogue] = useState<SourceCatalogue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [query, setQuery] = useState("");
  const [state, setState] = useState("");
  const pending = useRef(false);
  const requestVersion = useRef(0);

  const load = useCallback(() => {
    const version = ++requestVersion.current;
    return readCatalogue().then((data) => {
      if (version !== requestVersion.current) return;
      setCatalogue(data);
      setError(null);
    }).catch((reason: unknown) => {
      if (version === requestVersion.current) {
        setError(reason instanceof Error ? reason.message : "Le registre est indisponible.");
      }
    });
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    const form = document.getElementById("source-preparation");
    form?.focus({ preventScroll: true });
    form?.scrollIntoView({ block: "start", behavior: "instant" });
  }, [selectedId]);

  useEffect(() => {
    const controller = new AbortController();
    const version = ++requestVersion.current;
    void readCatalogue(controller.signal).then((data) => {
      if (version === requestVersion.current) setCatalogue(data);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setError(reason instanceof Error ? reason.message : "Le registre est indisponible.");
      }
    });
    return () => controller.abort();
  }, []);

  const selected = catalogue?.sources.find((source) => source.id === selectedId);
  const draft = selectedId ? drafts[selectedId] : undefined;
  const config = draft?.config ?? selected?.config;
  const selection = catalogue?.sources.filter((source) => {
    const term = query.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
    const text = `${source.id} ${source.name} ${source.competitions}`.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
    return (!state || source.historicalState === state) && text.includes(term);
  }) ?? [];

  function edit<K extends keyof Config>(key: K, value: Config[K]) {
    if (!selected || !catalogue) return;
    setDrafts((previous) => ({
      ...previous,
      [selected.id]: {
        revision: previous[selected.id]?.revision ?? catalogue.revision,
        config: { ...(previous[selected.id]?.config ?? selected.config), [key]: value },
      },
    }));
    setNotice("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !catalogue || !config || pending.current) return;
    pending.current = true;
    ++requestVersion.current;
    setBusy(true);
    setNotice("");
    try {
      const response = await fetch("/api/tipsters/sources", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(12_000),
        body: JSON.stringify({ sourceId: selected.id, expectedRevision: draft?.revision ?? catalogue.revision, config }),
      });
      const result = await response.json();
      if (!response.ok || result.status !== "saved") {
        throw new Error(result.message || "La préparation n’a pas pu être enregistrée. Votre brouillon est conservé.");
      }
      const current = await readCatalogue();
      setCatalogue(current);
      setDrafts((previous) => {
        const remaining = { ...previous };
        delete remaining[selected.id];
        return remaining;
      });
      setError(null);
      setNotice(`Préparation de ${selected.name} enregistrée. Révision ${result.revision.slice(0, 12)}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "La sauvegarde est indisponible.");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  async function reloadSelected() {
    if (!selected || pending.current) return;
    pending.current = true;
    ++requestVersion.current;
    setBusy(true);
    try {
      const current = await readCatalogue();
      setCatalogue(current);
      setDrafts((previous) => {
        const remaining = { ...previous };
        delete remaining[selected.id];
        return remaining;
      });
      setError(null);
      setNotice(`Réglages enregistrés de ${selected.name} rechargés.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Le rechargement a échoué.");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return <>
    <PageHeader eyebrow="Dossier fidèle · Administration" title="Paramétrage des sources tipsters"
      subtitle="Préparez les sources candidates à partir du registre et de leurs contrôles historiques." />
    <nav className="pilot-actions" aria-label="Administration des sources">
      <InlineLink href="/expert/admin-collecte">Suivi du pilote autorisé</InlineLink>
      <InlineLink href="/expert/tipsters">Fiches tipsters</InlineLink>
      <button className="pilot-button" type="button" disabled={busy} onClick={() => void load()}>Actualiser le registre</button>
    </nav>
    {error && <p className="pilot-alert" role="alert">{error}</p>}
    <p role="status" aria-live="polite">{notice}</p>
    {catalogue ? <>
      <div className="metrics-grid source-observatory-metrics">
        <MetricCard label="Sources du registre" value={formatNumber(catalogue.total)} detail="Inventaire historique complet" />
        <MetricCard label="À construire" value={formatNumber(catalogue.counts.a_construire ?? 0)} detail="État déclaré dans le registre" />
        <MetricCard label="Manuelles" value={formatNumber(catalogue.counts.manuel ?? 0)} detail="Accès manuel historique" />
        <MetricCard label="Bloquées" value={formatNumber(catalogue.counts.bloque ?? 0)} detail="Blocage déclaré dans le registre" />
        <MetricCard label="Préparations enregistrées" value={formatNumber(catalogue.prepared)} detail="Réglages locaux à revalider avant collecte" />
      </div>
      <EvidenceNote>Le pilote J12 autorisé utilise {catalogue.pilotProvider.name}, avec un plafond de {catalogue.pilotProvider.requestsMax} requêtes. Les préparations de ce registre servent aux futures collectes.</EvidenceNote>
      <section className="section-card">
        <SectionHeading title="Registre des sources candidates" />
        <div className="filter-panel pilot-filters">
          <label><span>Rechercher une source</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
          <label><span>État historique</span><select value={state} onChange={(event) => setState(event.target.value)}>
            <option value="">Tous les états</option>
            {Object.entries(stateLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        </div>
        <p role="status">{selection.length} source{selection.length > 1 ? "s" : ""} affichée{selection.length > 1 ? "s" : ""} sur {catalogue.total}.</p>
        <div className="table-scroll source-catalogue-table" role="region" aria-label="Sources du registre" tabIndex={0}><table>
          <caption>Sources candidates et préparation locale</caption>
          <thead><tr><th scope="col">Source</th><th scope="col">État historique</th><th scope="col">Préparation</th><th scope="col">Fiche</th></tr></thead>
          <tbody>{selection.map((source) => <tr key={source.id}>
            <th scope="row">{source.name}<br /><small>{source.id}</small></th>
            <td>{stateLabels[source.historicalState]}</td>
            <td>{drafts[source.id] ? "Brouillon conservé" : source.prepared ? "Enregistrée, à revalider" : "Valeurs proposées"}</td>
            <td><button className="pilot-button" type="button" disabled={busy} aria-controls="source-preparation" onClick={() => { setSelectedId(source.id); setNotice(""); }}>Configurer {source.id}</button></td>
          </tr>)}</tbody>
        </table></div>
      </section>
      {selected && config && <section className="section-card" id="source-preparation" tabIndex={-1}>
        <SectionHeading title={`Préparation locale · ${selected.name}`} />
        <p>État historique {stateLabels[selected.historicalState]}. Contrôle archivé du {selected.historicalCheckedAt}.</p>
        <p><a className="inline-link" href={selected.url} target="_blank" rel="noopener noreferrer">Ouvrir la source publique</a></p>
        <details><summary>Accès, conditions et limites archivés</summary><p>{selected.historicalAccess}</p><p>{selected.historicalTerms}</p><p>{selected.limits}</p></details>
        <p>{selected.savedAt ? `Dernière sauvegarde le ${formatDateTime(selected.savedAt, true)}, heure de Paris.` : "Paramètres initiaux proposés à partir du registre."}</p>
        {draft && <p>Ce brouillon est conservé lorsque vous consultez une autre source.</p>}
        <form className="source-preparation-form" onSubmit={(event) => void save(event)}>
          <fieldset disabled={busy}>
          <label><span>Adresse publique de collecte prévue</span><input type="url" required maxLength={1000} value={config.endpoint} onChange={(event) => edit("endpoint", event.target.value)} /></label>
          <label><span>Format de lecture prévu</span><select value={config.adapter} onChange={(event) => edit("adapter", event.target.value as Config["adapter"])}>
            {Object.entries(adapterLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <label><span>Intervalle prévu entre visites, en minutes</span><input type="number" required min={30} max={1440} step={1} value={config.intervalMinutes} onChange={(event) => edit("intervalMinutes", Number(event.target.value))} /></label>
          <label><span>Plafond prévu de requêtes par visite</span><input type="number" required min={1} max={10} step={1} value={config.requestsPerVisit} onChange={(event) => edit("requestsPerVisit", Number(event.target.value))} /></label>
          <label><span>Notes de préparation</span><textarea maxLength={2000} rows={4} value={config.notes} onChange={(event) => edit("notes", event.target.value)} /></label>
          <div className="pilot-actions">
            <button className="pilot-button" disabled={busy} type="submit">{busy ? "Enregistrement…" : "Enregistrer la préparation"}</button>
            <button className="pilot-button" disabled={busy} type="button" onClick={() => void reloadSelected()}>Recharger les réglages enregistrés</button>
          </div>
          </fieldset>
        </form>
        <EvidenceNote>L’accès actuel, les droits d’usage et l’extraction de pronostics restent à vérifier avant d’inclure cette source dans une nouvelle collecte.</EvidenceNote>
      </section>}
    </> : !error && <EmptyState title="Chargement du registre" text="Lecture des sources et de leur préparation locale." />}
  </>;
}
