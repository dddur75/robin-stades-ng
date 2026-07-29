"use client";

import { useEffect, useMemo, useState } from "react";

import { formatNumber, formatPercent } from "../../i18n";
import { hypothesisIntelligence } from "../../lib/presentation";
import { StatusBadge } from "../common/ui";

type ExpertRule = {
  id: string;
  origin: string;
  title: string;
  family: string;
  familyId: string;
  parentRuleId: string;
  variantCount: number;
  market: string;
  selection: string;
  competition: string;
  oddsBand: number[] | null;
  maximumMargin: number | null;
  support: number;
  roi: number | null;
  qValue: number | null;
  drawdown: number | null;
  liveObservable: boolean;
  status: string;
  ruleHash: string;
  payloadHash: string;
  canonicalFingerprint: string;
  discoveryRun: string;
  discoveryRevision: string;
  negativeControls: string[];
  statusHistory: string[];
  prospectiveContract: string | null;
  ranking: {
    overall_exploratory_priority: number;
    uncertainty_rank: number;
    stability_rank: number;
  } | null;
};

type ExpertPagePayload = {
  page: number;
  page_size: number;
  total: number;
  items: ExpertRule[];
};

type LoadedPage = {
  page: number;
  payload: ExpertPagePayload | null;
  error: string;
};

const ALL = "ALL";

export function HypothesisExplorer() {
  const explorer = hypothesisIntelligence.expertExplorer;
  const [page, setPage] = useState(1);
  const [loaded, setLoaded] = useState<LoadedPage>({
    page: 0,
    payload: null,
    error: "",
  });
  const [origin, setOrigin] = useState(ALL);
  const [market, setMarket] = useState(ALL);
  const [selection, setSelection] = useState(ALL);
  const [competition, setCompetition] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [minimumSupport, setMinimumSupport] = useState(0);
  const [sort, setSort] = useState("priority");

  useEffect(() => {
    const manifest = explorer.pageManifest.find((item) => item.page === page);
    if (!manifest) return;
    let active = true;
    fetch(manifest.url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<ExpertPagePayload>;
      })
      .then((data) => {
        if (active) setLoaded({ page, payload: data, error: "" });
      })
      .catch((reason: unknown) => {
        if (active) {
          setLoaded({ page, payload: null, error: String(reason) });
        }
      });
    return () => {
      active = false;
    };
  }, [explorer.pageManifest, page]);

  const payload = loaded.page === page ? loaded.payload : null;
  const error = loaded.page === page ? loaded.error : "";

  const rows = useMemo(() => {
    const filtered = (payload?.items ?? []).filter(
      (row) =>
        (origin === ALL || row.origin === origin) &&
        (market === ALL || row.market === market) &&
        (selection === ALL || row.selection === selection) &&
        (competition === ALL || row.competition === competition) &&
        (status === ALL || row.status === status) &&
        row.support >= minimumSupport,
    );
    return [...filtered].sort((left, right) => {
      if (sort === "support") return right.support - left.support;
      if (sort === "roi") return (right.roi ?? -Infinity) - (left.roi ?? -Infinity);
      if (sort === "uncertainty") {
        return (left.ranking?.uncertainty_rank ?? Infinity)
          - (right.ranking?.uncertainty_rank ?? Infinity);
      }
      if (sort === "stability") {
        return (left.ranking?.stability_rank ?? Infinity)
          - (right.ranking?.stability_rank ?? Infinity);
      }
      return (right.ranking?.overall_exploratory_priority ?? 0)
        - (left.ranking?.overall_exploratory_priority ?? 0);
    });
  }, [
    competition,
    market,
    minimumSupport,
    origin,
    payload,
    selection,
    sort,
    status,
  ]);

  const options = (key: keyof ExpertRule) =>
    Array.from(
      new Set((payload?.items ?? []).map((row) => String(row[key]))),
    ).sort((left, right) => left.localeCompare(right, "fr-FR"));

  return (
    <div className="hypothesis-explorer">
      <div className="hypothesis-explorer-summary">
        <strong>{formatNumber(explorer.total)} règles</strong>
        <span>{formatNumber(explorer.pages)} pages vérifiées</span>
        <span>{formatNumber(explorer.pageSize)} règles chargées au maximum</span>
      </div>
      <div className="hypothesis-filters" aria-label="Filtres des hypothèses">
        <label>Origine<select value={origin} onChange={(event) => setOrigin(event.target.value)}><option value={ALL}>Toutes</option>{options("origin").map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Marché<select value={market} onChange={(event) => setMarket(event.target.value)}><option value={ALL}>Tous</option>{options("market").map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Sélection<select value={selection} onChange={(event) => setSelection(event.target.value)}><option value={ALL}>Toutes</option>{options("selection").map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Compétition<select value={competition} onChange={(event) => setCompetition(event.target.value)}><option value={ALL}>Toutes</option>{options("competition").map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Statut<select value={status} onChange={(event) => setStatus(event.target.value)}><option value={ALL}>Tous</option>{options("status").map((value) => <option key={value}>{value}</option>)}</select></label>
        <label>Support minimum<input min="0" onChange={(event) => setMinimumSupport(Number(event.target.value))} type="number" value={minimumSupport} /></label>
        <label>Tri<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="priority">Priorité exploratoire</option><option value="support">Support</option><option value="roi">ROI brut</option><option value="uncertainty">Incertitude</option><option value="stability">Stabilité</option></select></label>
      </div>

      {error ? <p className="table-empty">Page indisponible : {error}</p> : null}
      {!payload && !error ? <p className="table-empty">Chargement de la page vérifiée…</p> : null}
      {payload ? (
        <div className="hypothesis-rule-list">
          {rows.map((row) => (
            <article className="expert-rule-card" key={row.id}>
              <div className="hypothesis-card-head">
                <span>{row.id}</span>
                <StatusBadge value={row.status} />
              </div>
              <h3>{row.title}</h3>
              <p>{row.competition} · {row.market} · {row.selection}</p>
              <dl className="discovery-metrics">
                <div><dt>Support</dt><dd>{formatNumber(row.support)}</dd></div>
                <div><dt>ROI brut</dt><dd>{formatPercent(row.roi)}</dd></div>
                <div><dt>q-value</dt><dd>{formatNumber(row.qValue ?? 0, 2)}</dd></div>
                <div><dt>Drawdown</dt><dd>{row.drawdown == null ? "—" : `${formatNumber(row.drawdown, 2)} u`}</dd></div>
                <div><dt>Cote</dt><dd>{row.oddsBand?.join("–") ?? "—"}</dd></div>
                <div><dt>Marge max.</dt><dd>{formatPercent(row.maximumMargin)}</dd></div>
              </dl>
              <details>
                <summary>Définition exécutable et preuves</summary>
                <dl className="technical-list">
                  <div><dt>Famille</dt><dd>{row.family}</dd></div>
                  <div><dt>Règle parent</dt><dd>{row.parentRuleId}</dd></div>
                  <div><dt>Variantes</dt><dd>{row.variantCount}</dd></div>
                  <div><dt>Run</dt><dd>{row.discoveryRun}</dd></div>
                  <div><dt>Révision</dt><dd>{row.discoveryRevision}</dd></div>
                  <div><dt>Empreinte règle</dt><dd>{row.ruleHash}</dd></div>
                  <div><dt>Empreinte payload</dt><dd>{row.payloadHash}</dd></div>
                  <div><dt>Contrôles</dt><dd>{row.negativeControls.join(" · ")}</dd></div>
                  <div><dt>Historique des statuts</dt><dd>{row.statusHistory.join(" → ")}</dd></div>
                  <div><dt>Contrat prospectif</dt><dd>{row.prospectiveContract ?? "Non sélectionné"}</dd></div>
                </dl>
              </details>
            </article>
          ))}
        </div>
      ) : null}

      <nav className="pagination" aria-label="Pagination des 700 règles">
        <button disabled={page === 1} onClick={() => setPage((value) => value - 1)} type="button">Page précédente</button>
        <span>Page {page} / {explorer.pages}</span>
        <button disabled={page === explorer.pages} onClick={() => setPage((value) => value + 1)} type="button">Page suivante</button>
      </nav>
    </div>
  );
}
