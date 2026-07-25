"use client";

import { useMemo, useState } from "react";
import snapshot from "./cockpit-data.json";

type PageKey =
  | "command"
  | "coverage"
  | "odds"
  | "matches"
  | "performance"
  | "quality"
  | "costs"
  | "explorer"
  | "deep"
  | "backfill"
  | "players"
  | "featureLab"
  | "modelLab"
  | "backtestLab"
  | "historicalQuality";

const pages: { key: PageKey; label: string; glyph: string }[] = [
  { key: "command", label: "Command Center", glyph: "⌂" },
  { key: "coverage", label: "Coverage Explorer", glyph: "▦" },
  { key: "odds", label: "Odds Explorer", glyph: "↗" },
  { key: "matches", label: "Match Center", glyph: "◉" },
  { key: "performance", label: "Shadow Performance", glyph: "◆" },
  { key: "quality", label: "Pipeline & Qualité", glyph: "✓" },
  { key: "costs", label: "Coûts & Quotas", glyph: "◒" },
  { key: "explorer", label: "Data Explorer", glyph: "⌘" },
  { key: "deep", label: "Deep Data Center", glyph: "D" },
  { key: "backfill", label: "Backfill Monitor", glyph: "B" },
  { key: "players", label: "Player Explorer", glyph: "P" },
  { key: "featureLab", label: "Feature Lab", glyph: "F" },
  { key: "modelLab", label: "Model Lab", glyph: "M" },
  { key: "backtestLab", label: "Backtest Explorer", glyph: "T" },
  { key: "historicalQuality", label: "Historical Quality", glyph: "Q" },
];

const labels: Record<PageKey, { eyebrow: string; title: string; note: string }> = {
  command: {
    eyebrow: "Vue opérationnelle",
    title: "Command Center",
    note: "État consolidé de la chaîne prospective, sans argent réel.",
  },
  matches: {
    eyebrow: "Calendrier & modèles",
    title: "Match Center",
    note: "Fixtures, probabilités et qualité au même endroit.",
  },
  odds: {
    eyebrow: "Marché horodaté",
    title: "Odds Explorer",
    note: "Mouvements, dispersion et fraîcheur des snapshots append-only.",
  },
  coverage: {
    eyebrow: "Fenêtres & disponibilité",
    title: "Coverage Explorer",
    note: "Sépare marché absent, collecte manquée et panne fournisseur.",
  },
  performance: {
    eyebrow: "Trois preuves séparées",
    title: "Shadow Performance",
    note: "Legacy, OOS historique et shadow prospectif ne sont jamais fusionnés.",
  },
  quality: {
    eyebrow: "Contrôles & provenance",
    title: "Pipeline & Qualité",
    note: "Exécutions, stockage, incidents, SLO et fournisseurs.",
  },
  costs: {
    eyebrow: "Budget adaptatif",
    title: "Coûts & Quotas",
    note: "Consommation, prévision, réserve et scénarios informatifs.",
  },
  explorer: {
    eyebrow: "Données bornées",
    title: "Data Explorer",
    note: "Filtrer, trier, segmenter et exporter la preuve publiée.",
  },
  deep: {
    eyebrow: "Usine historique autonome",
    title: "Deep Data Command Center",
    note: "Backfill, quota, couverture et stockage, séparés du shadow prospectif.",
  },
  backfill: {
    eyebrow: "Lots bornés et reprenables",
    title: "Backfill Monitor",
    note: "État des tâches, checkpoints et prochaine unité de travail.",
  },
  players: {
    eyebrow: "Données joueurs sourcées",
    title: "Player Explorer",
    note: "Profils et statistiques observées, sans zéro inventé.",
  },
  featureLab: {
    eyebrow: "Point-in-time strict",
    title: "Feature Lab",
    note: "Définitions, statut, couverture et risque de fuite.",
  },
  modelLab: {
    eyebrow: "Probabilités interprétables",
    title: "Model Lab",
    note: "Log Loss, Brier, calibration et modèles bloqués par la couverture.",
  },
  backtestLab: {
    eyebrow: "Discovery · validation · OOS",
    title: "Backtest Explorer",
    note: "Résultats historiques séparés du live, sans promotion automatique.",
  },
  historicalQuality: {
    eyebrow: "Qualité historique",
    title: "Historical Data Quality",
    note: "Couverture, quarantaines, temporalité et intégrité des partitions.",
  },
};

function SourceBadge({ origin }: { origin: string }) {
  const token = origin.toLowerCase().replace(" source", "").replace(" data", "").replaceAll(" ", "-");
  return <span className={`source-badge ${token}`}>{origin}</span>;
}

function StatusPill({ value }: { value: string }) {
  const token = value.toLowerCase().replaceAll("_", "-").replaceAll(" ", "-");
  return <span className={`status-pill ${token}`}>{value.replaceAll("_", " ")}</span>;
}

function Metric({
  label,
  value,
  detail,
  tone = "",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <article className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function EmptyState({
  title,
  text,
  label,
}: {
  title: string;
  text: string;
  label: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-mark">∅</div>
      <div>
        <SourceBadge origin={label} />
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
    </div>
  );
}

function pct(value: number | null) {
  return value === null ? "—" : `${(value * 100).toFixed(1)} %`;
}

function dateTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Paris",
  }).format(new Date(value));
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const columns = Object.keys(rows[0]);
  const escape = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [
    columns.map(escape).join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function Home() {
  const [page, setPage] = useState<PageKey>("command");
  const [competition, setCompetition] = useState("Ligue 1 - France");
  const [period, setPeriod] = useState("30 prochains jours");
  const [market, setMarket] = useState("1X2");
  const [strategy, setStrategy] = useState("Toutes");
  const [model, setModel] = useState("Tous");
  const [status, setStatus] = useState("Tous");
  const [quality, setQuality] = useState("Toutes");
  const [bookmaker, setBookmaker] = useState("Tous");
  const [filtersOpen, setFiltersOpen] = useState(false);

  const filteredMatches = useMemo(
    () =>
      snapshot.matches.filter(
        (match) =>
          match.competition === competition &&
          (model === "Tous" || match.model === model) &&
          (quality === "Toutes" || match.quality === quality),
      ),
    [competition, model, quality],
  );

  const title = labels[page];

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">R</div>
          <div>
            <strong>Robin</strong>
            <span>des Stades</span>
          </div>
        </div>
        <div className="mode">
          <span className="pulse" />
          Shadow mode
          <small>simulation stricte</small>
        </div>
        <nav aria-label="Navigation principale">
          {pages.map((item) => (
            <button
              className={page === item.key ? "active" : ""}
              key={item.key}
              onClick={() => setPage(item.key)}
            >
              <span>{item.glyph}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span>Système</span>
          <strong>{snapshot.productionStatus}</strong>
          <small>Aucune exécution financière</small>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="mobile-brand">
            <span>R</span> Robin des Stades
          </div>
          <div className="system-state">
            <span className="pulse" />
            {snapshot.shadowStatus.replaceAll("_", " ")}
          </div>
          <div className="top-actions">
            <span>Actualisé {dateTime(snapshot.generatedAt)}</span>
            <button onClick={() => setFiltersOpen(!filtersOpen)}>Filtres</button>
          </div>
        </header>

        <div className="content">
          <div className="page-head">
            <div>
              <span className="eyebrow">{title.eyebrow}</span>
              <h1>{title.title}</h1>
              <p>{title.note}</p>
            </div>
            <div className="lock">
              <span>●</span>
              <div>
                <strong>{snapshot.productionStatus}</strong>
                <small>Shadow-only · mise réelle désactivée</small>
              </div>
            </div>
          </div>

          <section className={`filters ${filtersOpen ? "open" : ""}`}>
            <label>
              Période
              <select value={period} onChange={(event) => setPeriod(event.target.value)}>
                {snapshot.filters.periods.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Compétition
              <select value={competition} onChange={(event) => setCompetition(event.target.value)}>
                {snapshot.filters.competitions.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Marché
              <select value={market} onChange={(event) => setMarket(event.target.value)}>
                {snapshot.filters.markets.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Stratégie
              <select value={strategy} onChange={(event) => setStrategy(event.target.value)}>
                {snapshot.filters.strategies.map((item) => (
                  <option key={item}>{item.replaceAll("_", " ")}</option>
                ))}
              </select>
            </label>
            <label>
              Modèle
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                <option>Tous</option>
                {snapshot.filters.models.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Statut
              <select value={status} onChange={(event) => setStatus(event.target.value)}>
                {snapshot.filters.statuses.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Qualité
              <select value={quality} onChange={(event) => setQuality(event.target.value)}>
                {snapshot.filters.qualities.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Bookmaker
              <select value={bookmaker} onChange={(event) => setBookmaker(event.target.value)}>
                {snapshot.filters.bookmakers.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </section>

          {page === "command" && <CommandCenter onNavigate={setPage} />}
          {page === "coverage" && <CoverageExplorer />}
          {page === "matches" && <MatchCenter matches={filteredMatches} market={market} />}
          {page === "odds" && <OddsExplorer />}
          {page === "performance" && <ShadowPerformance />}
          {page === "quality" && <PipelineQuality />}
          {page === "costs" && <CostsQuotas />}
          {page === "explorer" && <DataExplorer />}
          {page === "deep" && <DeepDataCommandCenter />}
          {page === "backfill" && <BackfillMonitor />}
          {page === "players" && <PlayerExplorer />}
          {page === "featureLab" && <FeatureLab />}
          {page === "modelLab" && <ModelLab />}
          {page === "backtestLab" && <BacktestExplorer />}
          {page === "historicalQuality" && <HistoricalDataQuality />}
        </div>
      </section>
    </main>
  );
}

function CommandCenter({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  return (
    <>
      <section className="metric-grid">
        <Metric label="Fixtures suivies" value={String(snapshot.metrics.fixtures)} detail="fenêtre prospective" />
        <Metric label="Snapshots réels" value={String(snapshot.metrics.snapshots)} detail="2 payloads distincts" tone="cyan" />
        <Metric label="Registre PostgreSQL" value={String(snapshot.metrics.durableRecords)} detail="lignes métier uniques" tone="cyan" />
        <Metric label="Payloads physiques" value={String(snapshot.metrics.rawPayloads)} detail="5 observations · 2 doublons évités" />
        <Metric label="Burn-in" value="ACTIF" detail={snapshot.burnIn.health.replaceAll("_", " ")} tone="amber" />
        <Metric label="Quota restant" value={snapshot.metrics.quotaRemaining.toLocaleString("fr-FR")} detail="sur 20 000 crédits" />
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Funnel prospectif</span><h2>Du calendrier au règlement shadow</h2></div>
          <StatusPill value="LIVE_SHADOW" />
        </div>
        <div className="funnel">
          {snapshot.funnel.map((item, index) => (
            <div key={item.stage}>
              <span>{item.stage}</span>
              <strong>{item.count}</strong>
              {index > 0 && <small>{item.loss ? `−${item.loss}` : "stable"}</small>}
            </div>
          ))}
        </div>
        <div className="reason-grid">
          <div>
            <span>Pourquoi les matchs ne sont-ils pas analysables ?</span>
            {snapshot.notAnalyzableReasons.map((item) => (
              <p key={item.reason}>
                <strong>{item.count}</strong>
                <code>{item.reason}</code>
                <SourceBadge origin={item.origin} />
              </p>
            ))}
          </div>
          <div>
            <span>Prochaine étape automatique</span>
            <p><strong>J-7</strong><code>14 août 2026</code><StatusPill value="PENDING" /></p>
            <p><strong>120 min</strong><code>marge de rattrapage</code><StatusPill value="ACTIVE" /></p>
          </div>
        </div>
      </section>

      <section className="two-column">
        <article className="panel hero-panel">
          <div className="panel-head">
            <div><span>Pipeline autonome</span><h2>Chaîne sous contrôle</h2></div>
            <StatusPill value={snapshot.status} />
          </div>
          <div className="pipeline">
            {["Collecte", "Qualité", "Modèles", "Décision", "Règlement"].map((item, index) => (
              <div className={index < 4 ? "done" : "waiting"} key={item}>
                <i>{index < 4 ? "✓" : "…"}</i>
                <span>{item}</span>
                {index < 4 && <b />}
              </div>
            ))}
          </div>
          <p className="panel-note">{snapshot.message}</p>
          <div className="run-list">
            {snapshot.runs.map((run) => (
              <div key={run.id}>
                <span className="run-dot" />
                <div>
                  <strong>{run.pipeline}</strong>
                  <small>{dateTime(run.finishedAt)} · {run.records} entrées · coût {run.calls}</small>
                </div>
                <SourceBadge origin={run.origin} />
                <StatusPill value={run.status} />
              </div>
            ))}
          </div>
        </article>

        <article className="panel storage-card">
          <div className="panel-head">
            <div><span>Source de vérité</span><h2>Registre prospectif durable</h2></div>
            <StatusPill value={snapshot.durableStorage.bridge_status} />
          </div>
          <dl>
            <div><dt>Pont actif</dt><dd>branche orpheline shadow-data</dd></div>
            <div><dt>PostgreSQL</dt><dd>{snapshot.postgresql.status.replaceAll("_", " ")}</dd></div>
            <div><dt>Dernière écriture</dt><dd>{dateTime(snapshot.postgresql.last_write)}</dd></div>
            <div><dt>Lignes</dt><dd>{snapshot.postgresql.registry_records} uniques</dd></div>
            <div><dt>Retard pont</dt><dd>{snapshot.postgresql.bridge_lag_records} ligne</dd></div>
            <div><dt>Double écriture</dt><dd>{snapshot.doubleWrite.status}</dd></div>
            <div><dt>Capacité</dt><dd>{snapshot.postgresql.capacity_used_pct.toFixed(2)} % · {(snapshot.postgresql.database_size_bytes / 1_000_000).toFixed(2)} MB</dd></div>
            <div><dt>Burn-in</dt><dd>{snapshot.burnIn.technical} · {snapshot.burnIn.health.replaceAll("_", " ")}</dd></div>
            <div><dt>Migration</dt><dd>{snapshot.migration.coverage * 100} % · 0 erreur</dd></div>
            <div><dt>Replay</dt><dd>octets identiques · 0 appel API</dd></div>
            <div><dt>Artifacts</dt><dd>journal court uniquement</dd></div>
          </dl>
          <button className="text-button" onClick={() => onNavigate("quality")}>Inspecter stockage & incidents →</button>
        </article>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Garde-fous actifs</span><h2>Contrôles critiques</h2></div>
          <button className="text-button" onClick={() => onNavigate("quality")}>Voir les contrôles →</button>
        </div>
        <div className="guardrails">
          {[
            ["Fuite temporelle", "PASS", "cutoff strict"],
            ["Perte silencieuse", "PASS", "0 perte"],
            ["Persistance durable", "PASS", "shadow-data vérifié"],
            ["Quota mensuel", "PASS", "niveau NORMAL"],
          ].map(([name, status, detail]) => (
            <div key={name}><StatusPill value={status} /><strong>{name}</strong><small>{detail}</small></div>
          ))}
        </div>
      </section>
    </>
  );
}

function CoverageExplorer() {
  const rates = snapshot.coverageRates;
  return (
    <>
      <section className="quality-summary">
        <Metric label="Couverture fournisseur" value={`${(rates.provider * 100).toFixed(1)} %`} detail="marché réellement proposé" tone="cyan" />
        <Metric label="Couverture collecte" value="—" detail={rates.collectionStatus.replaceAll("_", " ")} />
        <Metric label="Couverture analytique" value={`${(rates.analytic * 100).toFixed(1)} %`} detail="fixture analysable" tone="amber" />
        <Metric label="Marge de reprise" value={`${snapshot.scheduler.recovery_margin_minutes} min`} detail="retard récupérable" />
      </section>
      <section className="panel">
        <div className="panel-head">
          <div><span>9 fenêtres par fixture</span><h2>Heatmap de couverture</h2></div>
          <StatusPill value="BURN_IN_ACTIVE" />
        </div>
        <div className="heatmap">
          <div className="heatmap-head">
            <span>Fixture</span>
            {snapshot.scheduler.windows.map((window) => <b key={window}>{window}</b>)}
          </div>
          {snapshot.coverage.map((item) => (
            <div className="heatmap-row" key={item.fixtureId}>
              <span><strong>{item.fixture}</strong><small>{dateTime(item.kickoff)}</small></span>
              {Object.entries(item.windows).map(([window, value]) => (
                <i className={String(value).toLowerCase().replaceAll("_", "-")} key={window} title={`${window} · ${value}`}>
                  {value === "PENDING" ? "·" : "✓"}
                </i>
              ))}
            </div>
          ))}
        </div>
        <div className="legend">
          <span><i className="pending" /> attendu</span>
          <span><i className="collected" /> reçu</span>
          <span><i className="collected-late" /> reçu tardivement</span>
          <span><i className="no-market-available" /> marché absent</span>
          <span><i className="provider-failed" /> fournisseur en échec</span>
          <span><i className="skipped-quota" /> quota protégé</span>
        </div>
        <p className="panel-note">
          Les deux snapshots actuels sont des diagnostics hors fenêtre. Ils prouvent le pipeline, mais ne gonflent pas artificiellement la couverture planifiée.
        </p>
      </section>
    </>
  );
}

function MatchCenter({ matches, market }: { matches: typeof snapshot.matches; market: string }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div><span>{matches.length} fixtures affichées</span><h2>Probabilités pré-match · {market}</h2></div>
        <SourceBadge origin="LIVE SOURCE" />
      </div>
      {matches.length === 0 ? (
        <EmptyState
          title="EN ATTENTE DE DONNÉES PROSPECTIVES"
          text="Modifiez le modèle ou le niveau de qualité."
          label="NO OUTPUT"
        />
      ) : (
        <div className="match-list">
          {matches.map((match) => (
            <article className="match-card" key={match.id}>
              <div className="match-meta"><span>{match.competition}</span><strong>{dateTime(match.kickoff)}</strong><SourceBadge origin={match.origin} /></div>
              <div className="teams"><strong>{match.home}</strong><span>vs</span><strong>{match.away}</strong></div>
              <div className="identity-strip">
                <span>Fixture interne<code>{match.internalId.slice(0, 13)}…</code></span>
                <span>ID fournisseur<code>{match.id.slice(0, 13)}…</code></span>
                <span>UTC<code>{match.kickoff}</code></span>
                <span>Stade<code>NO OUTPUT</code></span>
              </div>
              <div className="availability-strip">
                {[
                  ["Cotes", match.probabilities.home ? "LIVE" : "ABSENT"],
                  ["Résultats", "PENDING"],
                  ["Statistiques", "NO OUTPUT"],
                  ["Compositions", "NO OUTPUT"],
                  ["Blessures", "NO OUTPUT"],
                  ["Historique", "NOT USED"],
                ].map(([label, value]) => (
                  <span key={label}>{label}<b>{value}</b></span>
                ))}
              </div>
              <div className="probabilities">
                {[["1", match.probabilities.home], ["N", match.probabilities.draw], ["2", match.probabilities.away]].map(([label, value]) => (
                  <div key={String(label)}><span>{label}</span><strong>{pct(value as number | null)}</strong><i style={{ width: pct(value as number | null) }} /></div>
                ))}
              </div>
              <div className="match-foot">
                <span>Modèle : <b>{match.model}</b></span>
                <StatusPill value={match.quality} />
                <span>Décision : <b>{match.decision}</b></span>
              </div>
              <div className="explanation-grid">
                <p><span>Faits</span>Fixture et marché reçus avant calcul.</p>
                <p><span>Calcul</span>Probabilités implicites normalisées.</p>
                <p><span>Hypothèse</span>Consensus des bookmakers observés.</p>
                <p><span>Condition de changement</span>Nouveau snapshot durable ou qualité suffisante.</p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function OddsExplorer() {
  return (
    <section className="panel">
      <div className="panel-head">
        <div><span>Snapshots horodatés</span><h2>Marché 1X2 & Totaux</h2></div>
        <StatusPill value="LIVE_PIPELINE_VERIFIED" />
      </div>
      <div className="movement-grid">
        {snapshot.oddsMovement.map((item, index) => (
          <article key={item.snapshot_id}>
            <SourceBadge origin={item.origin} />
            <small>{dateTime(item.observed_at)}</small>
            <h3>{item.fixture}</h3>
            <div className="movement-values">
              <span>1 moyen<strong>{item.home_mean.toFixed(2)}</strong></span>
              <span>N moyen<strong>{item.draw_mean.toFixed(2)}</strong></span>
              <span>2 moyen<strong>{item.away_mean.toFixed(2)}</strong></span>
              <span>Variation<strong>{index === 0 ? "point initial" : "0,00"}</strong></span>
            </div>
          </article>
        ))}
      </div>
      <p className="panel-note">Payloads distincts, prix agrégés identiques : aucune variation n’est inventée.</p>
      <div className="snapshot-list">
        {snapshot.odds.map((item) => (
          <article key={item.snapshot_id}>
            <div>
              <SourceBadge origin="LIVE SOURCE" />
              <small>{dateTime(item.observed_at)}</small>
            </div>
            <h3>{item.home} <span>—</span> {item.away}</h3>
            <div className="snapshot-metrics">
              <span>Cotes<strong>{item.quotes}</strong></span>
              <span>Bookmakers<strong>{item.bookmakers}</strong></span>
              <span>Marchés<strong>{item.markets.join(" · ")}</strong></span>
              <span>Avant match<strong>{(item.time_to_kickoff_seconds / 3600).toFixed(1)} h</strong></span>
            </div>
            <code title={item.payload_hash}>
              payload {item.payload_hash.slice(0, 12)}…
            </code>
          </article>
        ))}
      </div>
      <div className="schema-strip">
        <span>snapshot_id</span><span>provider_event_id</span><span>bookmaker</span><span>market</span><span>observed_at</span><span>time_to_kickoff</span>
      </div>
    </section>
  );
}

function ShadowBets() {
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Journal immuable</span><h2>Candidats & rejets</h2></div><strong className="counter">{snapshot.decisions.length}</strong></div>
      <div className="decision-list">
        {snapshot.decisions.map((decision) => (
          <article key={decision.decision_id}>
            <div><SourceBadge origin={decision.origin} /><small>{dateTime(decision.decided_at)}</small></div>
            <h3>{decision.home} <span>—</span> {decision.away}</h3>
            <div className="decision-metrics">
              <span>Sélection<strong>{decision.selection}</strong></span>
              <span>Prob. modèle<strong>{pct(decision.model_probability)}</strong></span>
              <span>Cote<strong>{decision.odds_decimal?.toFixed(2) ?? "—"}</strong></span>
              <span>Mise fictive<strong>{decision.suggested_stake.toFixed(1)} u</strong></span>
            </div>
            <div className="reject"><StatusPill value="REJETÉ" /><strong>{decision.primary_reason}</strong><span>{decision.secondary_reasons.join(" · ")}</span></div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ShadowPerformance() {
  return (
    <>
      <section className="performance-boundaries">
        <article><SourceBadge origin="LEGACY SOURCE" /><h2>Legacy</h2><strong>4 226 matchs</strong><p>Contexte rétrospectif. Jamais fusionné avec le shadow.</p></article>
        <article><SourceBadge origin="OOS HISTORICAL" /><h2>OOS historique</h2><strong>{snapshot.strategies.length} stratégies</strong><p>Walk-forward informatif, non promotionnel.</p></article>
        <article><SourceBadge origin="LIVE SHADOW" /><h2>Prospectif live</h2><strong>0 pari réglé</strong><p>Burn-in technique actif depuis un jour calendaire.</p></article>
      </section>
      <div className="statistical-lock">
        <strong>{snapshot.burnIn.statistical_message}</strong>
        <span>Minimum avant le prochain jalon : {snapshot.burnIn.minimum_calendar_days_before_next_jalon} jours calendaires.</span>
      </div>
      <StrategyLab />
      <ShadowBets />
    </>
  );
}

function PipelineQuality() {
  return (
    <>
      <section className="quality-summary">
        <Metric label="PostgreSQL" value="CONNECTÉ" detail={`${snapshot.postgresql.registry_records} lignes · ${snapshot.postgresql.migration_revision}`} tone="cyan" />
        <Metric label="Double écriture" value="VÉRIFIÉE" detail="Neon + shadow-data" tone="cyan" />
        <Metric label="Retard du pont" value={String(snapshot.postgresql.bridge_lag_records)} detail="ligne manquante" />
        <Metric label="Capacité utilisée" value={`${snapshot.postgresql.capacity_used_pct.toFixed(2)} %`} detail={`${(snapshot.postgresql.database_size_bytes / 1_000_000).toFixed(2)} MB sur 0,5 GB`} />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Contrats de données</span><h2>Contrôles bloquants</h2></div><SourceBadge origin="LIVE SOURCE" /></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Contrôle</th><th>État</th><th>Valeur</th><th>Seuil</th><th>Origine</th></tr></thead>
            <tbody>{snapshot.qualityChecks.map((item) => (
              <tr key={item.check}><td>{item.check}</td><td><StatusPill value={item.status} /></td><td>{item.value}</td><td>{item.threshold}</td><td><SourceBadge origin={item.origin} /></td></tr>
            ))}</tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function CostsQuotas() {
  return (
    <>
      <section className="quality-summary">
        <Metric label="Crédits consommés" value={String(snapshot.metrics.quotaUsed)} detail="mesure fournisseur" tone="cyan" />
        <Metric label="Prévision mensuelle" value="720" detail="scénario courant" />
        <Metric label="Réserve protégée" value="4 000" detail="20 % du plan" tone="amber" />
        <Metric label="Coût stockage actuel" value="0 €" detail="pont temporaire shadow-data" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Budget adaptatif</span><h2>Quota The Odds API</h2></div><StatusPill value="NORMAL" /></div>
        <div className="quota-track"><i style={{ width: "0.2%" }} /><b style={{ left: "80%" }} /><span>8 utilisés</span><span>réserve à 80 %</span><span>20 000</span></div>
        <p className="panel-note">Les fenêtres proches du coup d’envoi restent prioritaires. Les extensions de marché sont les premières coupées en cas de pression quota.</p>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Scénarios informatifs</span><h2>Impact d’un changement de périmètre</h2></div><SourceBadge origin="TEST EVIDENCE" /></div>
        <div className="cost-grid">
          {snapshot.costScenarios.map((scenario) => (
            <article key={scenario.scope}><span>{scenario.scope}</span><strong>{scenario.credits} crédits/mois</strong><small>{scenario.competitions} compétition(s) · {scenario.markets} marchés</small></article>
          ))}
        </div>
      </section>
    </>
  );
}

function DataExplorer() {
  const [query, setQuery] = useState("");
  const [sortAsc, setSortAsc] = useState(true);
  const rows = useMemo(
    () => [...snapshot.dataExplorer]
      .filter((row) => `${row.fixture} ${row.competition} ${row.quality}`.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => (sortAsc ? 1 : -1) * a.date.localeCompare(b.date)),
    [query, sortAsc],
  );
  const exportRows = rows.map((row) => ({ ...row }));
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Vue publiée</span><h2>{rows.length} lignes traçables</h2></div><SourceBadge origin="LIVE SOURCE" /></div>
      <div className="explorer-tools">
        <input aria-label="Rechercher" placeholder="Fixture, compétition, qualité…" value={query} onChange={(event) => setQuery(event.target.value)} />
        <button onClick={() => setSortAsc(!sortAsc)}>Date {sortAsc ? "↑" : "↓"}</button>
        <button onClick={() => localStorage.setItem("robin-data-view", JSON.stringify({ query, sortAsc }))}>Sauver la vue</button>
        <button onClick={() => downloadCsv("robin-shadow-data.csv", exportRows)}>Exporter CSV</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Date</th><th>Fixture</th><th>Marché</th><th>Bookmakers</th><th>Snapshots</th><th>Modèle</th><th>Qualité</th><th>Provenance</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={`${row.date}-${row.fixture}`}><td>{dateTime(row.date)}</td><td>{row.fixture}</td><td>{row.market}</td><td>{row.bookmakers}</td><td>{row.snapshots}</td><td>{row.model}</td><td><StatusPill value={row.quality} /></td><td><SourceBadge origin={row.provenance} /></td></tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

function StrategyLab() {
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Walk-forward 2025–2026</span><h2>Résultats hors échantillon</h2></div><StatusPill value="NO_PROMOTION" /></div>
      <div className="strategy-grid">
        {snapshot.strategies.map((strategy) => {
          const positive = strategy.roiPct > 0;
          return (
            <article key={strategy.strategy} className={positive ? "positive" : ""}>
              <div><SourceBadge origin={strategy.origin} /><StatusPill value={strategy.status} /></div>
              <h3>{strategy.strategy.replaceAll("_", " ")}</h3>
              <strong className="strategy-roi">{positive ? "+" : ""}{strategy.roiPct.toFixed(2)} %</strong>
              <span>ROI · {strategy.bets} paris · DD {strategy.max_drawdown.toFixed(2)} u</span>
              <div className="mini-ci"><span>{strategy.ciLowPct} %</span><b /><span>{strategy.ciHighPct} %</span></div>
              <p>{strategy.note}</p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function DeepDataCommandCenter() {
  const deep = snapshot.deepData;
  const coverageTotal = Object.values(deep.coverageCounts).reduce(
    (sum, value) => sum + value,
    0,
  );
  return (
    <>
      <section className="metrics-grid">
        <Metric label="API-Football" value={deep.status.replaceAll("_", " ")} detail="clé serveur uniquement" tone="good" />
        <Metric label="Pilote L1 2025" value={deep.pilotStatus.replaceAll("_", " ")} detail={`${deep.quota.calls} appels`} />
        <Metric label="Backfill" value={deep.backfillStatus.replaceAll("_", " ")} detail={`${deep.remainingTasks} tâches restantes`} />
        <Metric label="Couverture" value={`${coverageTotal} scopes`} detail={`${deep.coverageCounts.AVAILABLE ?? 0} disponibles`} />
        <Metric label="Quota restant" value={deep.quota.remaining == null ? "—" : String(deep.quota.remaining)} detail={`${deep.quota.mode} · réserve ${deep.quota.reserve}`} />
        <Metric label="Stockage brut" value={`${(deep.storage.rawBytes / 1_048_576).toFixed(1)} MiB`} detail={deep.storage.backend} />
        <Metric label="Parquet" value={`${(deep.storage.parquetBytes / 1_048_576).toFixed(1)} MiB`} detail="partitions versionnées" />
        <Metric label="ETA priorité A" value={`${deep.progress.etaPriorityADays ?? "—"} jours`} detail={`${deep.progress.callsPerDay ?? "—"} appels/jour`} />
        <Metric label="ETA priorité B" value={`${deep.progress.etaPriorityBDays ?? "—"} jours`} detail={`globale ${deep.progress.etaFullDays ?? "—"} jours`} />
        <Metric label="Canonicalité L1" value={`${deep.canonicality.canonical_fixtures ?? 0}/${deep.canonicality.received_fixtures ?? 0}`} detail={`${deep.canonicality.canonical_teams ?? 0}/${deep.canonicality.received_teams ?? 0} équipes`} />
        <Metric label="Isolation" value={deep.isolation.status.replaceAll("_", " ")} detail={`${deep.isolation.liveBranch} / ${deep.isolation.historicalBranch}`} tone="good" />
        <Metric label="Bundles" value={String(deep.storage.bundleCount)} detail={`${deep.storage.fileCount} fichiers · ${deep.storage.capacityStatus}`} />
        <Metric label="Features joueurs" value={deep.playerReadiness.status.replaceAll("_", " ")} detail={deep.playerReadiness.temporality} tone="warning" />
        <Metric label="Production" value={deep.productionStatus} detail="aucun pari réel" tone="warning" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Contrats de provenance</span><h2>Origines strictement séparées</h2></div><StatusPill value="AUDITABLE" /></div>
        <div className="cost-grid">
          {deep.origins.map((origin) => <article key={origin}><SourceBadge origin={origin} /><small>Données jamais requalifiées implicitement</small></article>)}
        </div>
      </section>
    </>
  );
}

function BackfillMonitor() {
  const deep = snapshot.deepData;
  return (
    <>
      <section className="metrics-grid">
        {Object.entries(deep.taskCounts).map(([status, count]) => (
          <Metric key={status} label={status.replaceAll("_", " ")} value={String(count)} detail="tâches historisées" />
        ))}
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Ordonnancement</span><h2>Prochaine tâche</h2></div><StatusPill value={deep.backfillStatus} /></div>
        {deep.nextTask ? (
          <pre>{JSON.stringify(deep.nextTask, null, 2)}</pre>
        ) : <EmptyState title="Aucune tâche publiée" text="Le plan sera alimenté après validation live des identifiants fournisseur." label="NO OUTPUT" />}
      </section>
    </>
  );
}

type PlayerRow = {
  id: number | null;
  name: string | null;
  age: number | null;
  position: string | null;
  appearances: number | null;
  minutes: number | null;
  rating: string | null;
  goals: number | null;
  assists: number | null;
  origin: string;
};

function PlayerExplorer() {
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState("Toutes");
  const players = snapshot.deepData.players as PlayerRow[];
  const positions = ["Toutes", ...new Set(players.map((player) => player.position).filter(Boolean) as string[])];
  const rows = players.filter((player) =>
    String(player.name ?? "").toLowerCase().includes(query.toLowerCase()) &&
    (position === "Toutes" || player.position === position));
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Échantillon du pilote</span><h2>{rows.length} joueurs tracés</h2></div><SourceBadge origin="HISTORICAL POINT-IN-TIME" /></div>
      <div className="explorer-tools"><input aria-label="Rechercher un joueur" placeholder="Nom du joueur…" value={query} onChange={(event) => setQuery(event.target.value)} /><select value={position} onChange={(event) => setPosition(event.target.value)}>{positions.map((item) => <option key={item}>{item}</option>)}</select></div>
      {rows.length ? <div className="table-wrap"><table><thead><tr><th>Joueur</th><th>Poste</th><th>Âge</th><th>App.</th><th>Minutes</th><th>Buts</th><th>Passes</th><th>Note</th><th>Source</th></tr></thead><tbody>
        {rows.map((player) => <tr key={String(player.id)}><td>{player.name}</td><td>{player.position ?? "—"}</td><td>{player.age ?? "—"}</td><td>{player.appearances ?? "—"}</td><td>{player.minutes ?? "—"}</td><td>{player.goals ?? "—"}</td><td>{player.assists ?? "—"}</td><td>{player.rating ?? "—"}</td><td><SourceBadge origin={player.origin} /></td></tr>)}
      </tbody></table></div> : <EmptyState title="Joueurs en attente" text="Le pilote Ligue 1 2025 alimentera cette vue sans données de démonstration." label="NO OUTPUT" />}
    </section>
  );
}

function FeatureLab() {
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Registre versionné</span><h2>Features point-in-time</h2></div><StatusPill value={snapshot.deepData.dataset.status ?? "WAITING"} /></div>
      <div className="table-wrap"><table><thead><tr><th>Feature</th><th>Version</th><th>Statut</th><th>Risque de fuite</th><th>Origine</th></tr></thead><tbody>
        {snapshot.deepData.featureCatalog.map((feature) => <tr key={feature.name}><td>{feature.name}</td><td>{feature.version}</td><td><StatusPill value={feature.status} /></td><td>{feature.leakageRisk}</td><td><SourceBadge origin={feature.origin} /></td></tr>)}
      </tbody></table></div>
    </section>
  );
}

function ModelLab() {
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Comparaison probabiliste</span><h2>Modèles et couverture</h2></div><StatusPill value="PRODUCTION_LOCKED" /></div>
      <div className="table-wrap"><table><thead><tr><th>Modèle</th><th>Version</th><th>Log Loss OOS</th><th>Brier OOS</th><th>Statut</th><th>Origine</th></tr></thead><tbody>
        {snapshot.deepData.models.map((model) => <tr key={model.name}><td>{model.name}</td><td>{model.version}</td><td>{model.logLoss == null ? "—" : model.logLoss.toFixed(4)}</td><td>{model.brier == null ? "—" : model.brier.toFixed(4)}</td><td><StatusPill value={model.status} /></td><td><SourceBadge origin={model.origin} /></td></tr>)}
      </tbody></table></div>
    </section>
  );
}

function BacktestExplorer() {
  const rows = snapshot.deepData.backtests;
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Walk-forward historique</span><h2>Résultats OOS séparés</h2></div><StatusPill value="NO_PROMOTION" /></div>
      {rows.length ? <div className="table-wrap"><table><thead><tr><th>Stratégie</th><th>Marché</th><th>Paris</th><th>ROI</th><th>Drawdown</th><th>Statut</th><th>Origine</th></tr></thead><tbody>
        {rows.map((row) => <tr key={row.strategy}><td>{row.strategy}</td><td>{row.market}</td><td>{row.bets}</td><td>{row.roi == null ? "—" : `${(row.roi * 100).toFixed(2)} %`}</td><td>{row.max_drawdown_units.toFixed(2)} u</td><td><StatusPill value={row.status} /></td><td><SourceBadge origin={row.origin} /></td></tr>)}
      </tbody></table></div> : <EmptyState title="Backtest en attente" text="Aucun résultat n'est inventé tant que le dataset temporel n'existe pas." label="NO OUTPUT" />}
    </section>
  );
}

function HistoricalDataQuality() {
  const deep = snapshot.deepData;
  return (
    <>
      <section className="metrics-grid">
        <Metric label="Qualité globale" value={deep.qualityStatus} detail="Parquet, hashes et temporalité" />
        <Metric label="Partitions" value={String(deep.quality.parquet_partitions ?? 0)} detail="partitions contrôlées" />
        <Metric label="Payloads bruts" value={String(deep.quality.raw_observations ?? 0)} detail="observations gzip" />
        <Metric label="Échecs" value={String(deep.quality.failures?.length ?? 0)} detail="exclus des modèles" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Matrice fournisseur</span><h2>Couverture par statut</h2></div><SourceBadge origin="HISTORICAL POINT-IN-TIME" /></div>
        <div className="cost-grid">{Object.entries(deep.coverageCounts).map(([status, count]) => <article key={status}><span>{status}</span><strong>{count}</strong><small>combinaisons compétition · saison · endpoint</small></article>)}</div>
      </section>
    </>
  );
}
