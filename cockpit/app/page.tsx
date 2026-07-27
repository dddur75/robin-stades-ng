"use client";

import { useMemo, useState } from "react";
import snapshot from "./cockpit-data.json";

type PageKey =
  | "command"
  | "robinLive"
  | "coverage"
  | "odds"
  | "matches"
  | "performance"
  | "quality"
  | "costs"
  | "explorer"
  | "deep"
  | "backfill"
  | "datasetReadiness"
  | "players"
  | "lineups"
  | "featureLab"
  | "modelLab"
  | "modelArena"
  | "externalValidation"
  | "criticalClosure"
  | "strategyLab"
  | "backtestLab"
  | "historicalQuality";

const pages: { key: PageKey; label: string; glyph: string }[] = [
  { key: "robinLive", label: "Robin Live V1", glyph: "V1" },
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
  { key: "datasetReadiness", label: "Dataset Readiness", glyph: "G" },
  { key: "players", label: "Player Explorer", glyph: "P" },
  { key: "lineups", label: "Lineup Explorer", glyph: "L" },
  { key: "featureLab", label: "Feature Lab", glyph: "F" },
  { key: "modelLab", label: "Model Lab", glyph: "M" },
  { key: "modelArena", label: "Model Arena", glyph: "A" },
  { key: "externalValidation", label: "External Validation", glyph: "X" },
  { key: "criticalClosure", label: "Market & Storage", glyph: "R" },
  { key: "strategyLab", label: "Strategy Lab", glyph: "S" },
  { key: "backtestLab", label: "Backtest Explorer", glyph: "T" },
  { key: "historicalQuality", label: "Historical Quality", glyph: "Q" },
];

const labels: Record<PageKey, { eyebrow: string; title: string; note: string }> = {
  robinLive: {
    eyebrow: "Preuve publique · shadow uniquement",
    title: "Robin Live V1",
    note: "Décisions, résultats et recherche publiés sans démo, pari réel ni promesse.",
  },
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
  datasetReadiness: {
    eyebrow: "Gates multi-saisons",
    title: "Dataset Readiness",
    note: "Couverture, qualité, temporalité et raisons des blocages.",
  },
  players: {
    eyebrow: "Données joueurs sourcées",
    title: "Player Explorer",
    note: "Profils et statistiques observées, sans zéro inventé.",
  },
  lineups: {
    eyebrow: "Pré-lineup vs simulé",
    title: "Lineup Explorer",
    note: "Onze attendu et composition historique simulée restent séparés.",
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
  modelArena: {
    eyebrow: "Validation appariée · cross-fit · bootstrap",
    title: "Scientific Model Arena",
    note: "Comparaisons exactes, intervalles groupés et contrôles négatifs sans promotion automatique.",
  },
  externalValidation: {
    eyebrow: "Multi-ligues · protocole gelé · aucun retuning",
    title: "External Validation",
    note: "Transfert, modèles spécifiques, pooled et leave-one-league-out, strictement conditionnés par les gates.",
  },
  criticalClosure: {
    eyebrow: "Gates critiques · marché réel · stockage durable",
    title: "Market & Storage Control Center",
    note: "Identités, joueurs, lineups, matching Football-Data et readiness R2 sans pari réel.",
  },
  strategyLab: {
    eyebrow: "Hypothèses sous contrôle",
    title: "Strategy Lab",
    note: "Sensibilité, tests multiples et aucune promotion automatique.",
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
          {page === "robinLive" && <RobinLive />}
          {page === "coverage" && <CoverageExplorer />}
          {page === "matches" && <MatchCenter matches={filteredMatches} market={market} />}
          {page === "odds" && <OddsExplorer />}
          {page === "performance" && <ShadowPerformance />}
          {page === "quality" && <PipelineQuality />}
          {page === "costs" && <CostsQuotas />}
          {page === "explorer" && <DataExplorer />}
          {page === "deep" && <DeepDataCommandCenter />}
          {page === "backfill" && <BackfillMonitor />}
          {page === "datasetReadiness" && <DatasetReadiness />}
          {page === "players" && <PlayerExplorer />}
          {page === "lineups" && <LineupExplorer />}
          {page === "featureLab" && <FeatureLab />}
          {page === "modelLab" && <ModelLab />}
          {page === "modelArena" && <ModelArena />}
          {page === "externalValidation" && <ExternalValidation />}
          {page === "criticalClosure" && <CriticalClosure />}
          {page === "strategyLab" && <HistoricalStrategyLab />}
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
      <section className="panel">
        <div className="panel-head">
          <div><span>Robin Live V1</span><h2>Preuve publique shadow</h2></div>
          <StatusPill value={snapshot.patternResearch.dataStatus} />
        </div>
        <div className="cost-grid">
          <article><span>Paris shadow</span><strong>{snapshot.patternResearch.today.shadowBets}</strong><small>simulation uniquement</small></article>
          <article><span>NO BET</span><strong>{snapshot.patternResearch.today.noBets}</strong><small>les absences sont publiées</small></article>
          <article><span>Bankroll shadow</span><strong>{snapshot.patternResearch.bankroll.currentUnits.toFixed(2)} u</strong><small>initiale 1 000 u</small></article>
          <article><span>Candidats</span><strong>{snapshot.patternResearch.strategies.shadowCandidates}</strong><small>aucune promotion automatique</small></article>
        </div>
        <p className="panel-note">
          {snapshot.patternResearch.methodology.warning} Données démo désactivées ·
          SOCIAL_PUBLISHING_ENABLED=false · {snapshot.patternResearch.productionStatus}.
        </p>
        <button className="text-button" onClick={() => onNavigate("robinLive")}>
          Ouvrir le registre Robin Live →
        </button>
      </section>

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

export function RobinLive() {
  const research = snapshot.patternResearch;
  const lab = research.laboratory;
  const bankroll = research.bankroll;
  return (
    <>
      <section className="metrics-grid">
        <Metric label="Matchs analysés" value={String(research.today.matchesAnalyzed)} detail="décisions publiées aujourd'hui" />
        <Metric label="Paris shadow" value={String(research.today.shadowBets)} detail="mise fictive fixe, jamais réelle" tone="cyan" />
        <Metric label="NO BET" value={String(research.today.noBets)} detail="absence de pari publiée" />
        <Metric label="Publication" value={dateTime(research.publicationTime)} detail={research.today.origin} />
        <Metric label="Données" value={research.dataStatus} detail="aucune démo présentée comme live" tone="amber" />
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Aujourd&apos;hui</span><h2>Décisions shadow et NO BET</h2></div>
          <SourceBadge origin={research.today.origin} />
        </div>
        {research.ledger.decisions === 0 ? (
          <EmptyState
            title="Zéro décision shadow publiée"
            text="Le registre reste vide tant qu'aucun candidat ne franchit les gates. Aucun exemple de démonstration n'est présenté comme réel."
            label="NO OUTPUT"
          />
        ) : (
          <div className="cost-grid">
            <article><span>Décisions</span><strong>{research.ledger.decisions}</strong><small>gelées avant kickoff</small></article>
            <article><span>Paris shadow</span><strong>{research.today.shadowBets}</strong><small>simulation uniquement</small></article>
            <article><span>NO BET</span><strong>{research.today.noBets}</strong><small>publiés avec justification</small></article>
            <article><span>Non classées</span><strong>{research.today.unclassifiedDecisions}</strong><small>jamais requalifiées en pari</small></article>
          </div>
        )}
        <p className="panel-note">{research.today.justification}</p>
      </section>

      <section className="two-column">
        <article className="panel">
          <div className="panel-head">
            <div><span>Résultats complets</span><h2>Règlements shadow</h2></div>
            <StatusPill value={research.ledger.status} />
          </div>
          <dl>
            <div><dt>Gagnés</dt><dd>{research.results.won}</dd></div>
            <div><dt>Perdus</dt><dd>{research.results.lost}</dd></div>
            <div><dt>Void</dt><dd>{research.results.void}</dd></div>
            <div><dt>Règlements</dt><dd>{research.results.settlements}</dd></div>
            <div><dt>Profit fictif</dt><dd>{research.results.profitUnits.toFixed(2)} u</dd></div>
            <div><dt>ROI shadow</dt><dd>{research.results.roi == null ? "N/A — aucun pari réglé" : pct(research.results.roi)}</dd></div>
            <div><dt>Registre</dt><dd>{research.results.historyRecords} enregistrements</dd></div>
          </dl>
        </article>

        <article className="panel">
          <div className="panel-head">
            <div><span>Bankroll fictive</span><h2>Trajectoire à mise fixe</h2></div>
            <StatusPill value="SIMULATION_ONLY" />
          </div>
          <dl>
            <div><dt>Initiale</dt><dd>{bankroll.initialUnits.toFixed(2)} u</dd></div>
            <div><dt>Actuelle</dt><dd>{bankroll.currentUnits.toFixed(2)} u</dd></div>
            <div><dt>Profit</dt><dd>{bankroll.profitUnits.toFixed(2)} u</dd></div>
            <div><dt>ROI</dt><dd>{bankroll.roi == null ? "N/A — aucune mise réglée" : pct(bankroll.roi)}</dd></div>
            <div><dt>Drawdown max</dt><dd>{bankroll.maxDrawdownUnits.toFixed(2)} u</dd></div>
            <div><dt>Courbe</dt><dd>{bankroll.curve.map((value) => Number(value).toFixed(2)).join(" → ")} u</dd></div>
          </dl>
          <p className="panel-note">Unités théoriques · aucune transaction · aucune connexion bookmaker.</p>
        </article>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Stratégies</span><h2>Recherche, shadow et rejets</h2></div>
          <StatusPill value={research.campaignVerdict} />
        </div>
        <div className="cost-grid">
          <article><span>Hypothèses exécutées</span><strong>{research.strategies.inResearch}</strong><small>recherche historique, pas des recommandations</small></article>
          <article><span>Candidates shadow</span><strong>{research.strategies.shadowCandidates}</strong><small>gates non contournables</small></article>
          <article><span>Rejets de support</span><strong>{research.strategies.supportRejected}</strong><small>167 inclus dans le total rejeté</small></article>
          <article><span>Rejetées de la promotion</span><strong>{research.strategies.promotionRejected}</strong><small>{research.strategies.rejectionReason}</small></article>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Laboratoire scientifique</span><h2>Hypothèses, FDR et contrôles négatifs</h2></div>
          <SourceBadge origin={research.researchStatus === "HISTORICAL_RESEARCH" ? "HISTORICAL RESEARCH" : "NO OUTPUT"} />
        </div>
        <div className="table-wrap"><table><thead><tr><th>Mesure</th><th>Nombre</th><th>Interprétation</th></tr></thead><tbody>
          <tr><td>Hypothèses générées</td><td>{lab.hypothesesGenerated}</td><td>univers déclaré</td></tr>
          <tr><td>Règles exécutées</td><td>{lab.rulesExecuted}</td><td>cache-only</td></tr>
          <tr><td>Rejets de support</td><td>{lab.supportRejected}</td><td>échantillon insuffisant</td></tr>
          <tr><td>Résultats positifs bruts</td><td>{lab.rawPositive}</td><td>non promotionnels</td></tr>
          <tr><td>Survivants FDR</td><td>{lab.fdrSurvivors}</td><td>{lab.pValueMethod} · {lab.fdrMethod}</td></tr>
          <tr><td>Walk-forward brut avant FDR</td><td>{lab.walkForwardRawBeforeFdr}</td><td>exploratoire, non promotionnel</td></tr>
          <tr><td>Survivants ligue externe</td><td>{lab.externalLeagueSurvivors}</td><td>transférabilité</td></tr>
          <tr><td>Contrôles négatifs</td><td>{lab.negativeControlsPassed}/{lab.negativeControls}</td><td>permutations et labels mélangés</td></tr>
        </tbody></table></div>
        <p className="panel-note"><StatusPill value={research.subVerdict} /></p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Exploration rejetée</span><h2>Trois meilleurs résultats bruts</h2></div>
          <StatusPill value="EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING" />
        </div>
        <div className="table-wrap"><table><thead><tr><th>Règle exposée</th><th>Support</th><th>ROI / IC 95 %</th><th>q-value</th><th>Folds</th><th>Stabilité ligue exposée</th><th>Statut</th><th>Limite</th></tr></thead><tbody>
          {lab.topExploratoryResults.map((row) => (
            <tr key={row.ruleHash}>
              <td>{row.competition} · {row.market} · {row.selection}</td>
              <td>{row.bets} paris · {row.bootstrapGroups} groupes</td>
              <td>{pct(row.roi)} · {row.bootstrapRoi95.length === 2 ? row.bootstrapRoi95.map((value) => pct(Number(value))).join(" / ") : "N/A"}</td>
              <td>{row.qValue.toFixed(2)}</td>
              <td>{row.positiveFolds}/{row.eligibleFolds}</td>
              <td>{row.leagueStability} · {row.exposedLeagueStability}</td>
              <td><StatusPill value={row.publicStatus} /></td>
              <td>{row.limit}</td>
            </tr>
          ))}
        </tbody></table></div>
        <p className="panel-note">Ces résultats sont exposés pour transparence. Ils échouent la correction des tests multiples et ne sont ni candidats, ni recommandations.</p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div><span>Méthodologie</span><h2>Lire Robin Live sans surinterpréter</h2></div>
          <StatusPill value={research.productionStatus} />
        </div>
        <div className="two-column">
          <article>
            <h3>WHAT_WAS_TESTED</h3>
            <ul>{research.WHAT_WAS_TESTED.map((item) => <li key={item}>{item}</li>)}</ul>
          </article>
          <article>
            <h3>WHAT_WAS_NOT_TESTED</h3>
            <ul>{research.WHAT_WAS_NOT_TESTED.map((item) => <li key={item}>{item}</li>)}</ul>
          </article>
        </div>
        <div className="guardrails">
          <div><StatusPill value="BACKTEST" /><strong>Historique</strong><small>{research.methodology.backtest}</small></div>
          <div><StatusPill value="SHADOW" /><strong>Simulation</strong><small>{research.methodology.shadow}</small></div>
          <div><StatusPill value="TRANSPARENCY" /><strong>Preuve complète</strong><small>{research.methodology.publication}</small></div>
          <div><StatusPill value="WARNING" /><strong>Aucune garantie</strong><small>{research.methodology.warning}</small></div>
        </div>
        <p className="panel-note">
          REAL_BETS=false · NO_BET_DEFAULT=true · SOCIAL_PUBLISHING_ENABLED=false ·
          données de démonstration désactivées.
        </p>
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
        <Metric label="ETA priorité A" value={`${deep.progress.etaPriorityA.base ?? "—"} jours`} detail={`${deep.progress.etaPriorityA.low ?? "—"} → ${deep.progress.etaPriorityA.high ?? "—"} jours`} />
        <Metric label="ETA priorité B" value={`${deep.progress.etaPriorityB.base ?? "—"} jours`} detail={`${deep.progress.etaPriorityB.low ?? "—"} → ${deep.progress.etaPriorityB.high ?? "—"} jours`} />
        <Metric label="ETA globale" value={`${deep.progress.etaFull.base ?? "—"} jours`} detail={`${deep.progress.etaFull.low ?? "—"} → ${deep.progress.etaFull.high ?? "—"} jours`} />
        <Metric label="Canonicalité L1" value={`${deep.canonicality.canonical_fixtures ?? 0}/${deep.canonicality.received_fixtures ?? 0}`} detail={`${deep.canonicality.canonical_teams ?? 0}/${deep.canonicality.received_teams ?? 0} équipes`} />
        <Metric label="Isolation" value={deep.isolation.status.replaceAll("_", " ")} detail={`${deep.isolation.liveBranch} / ${deep.isolation.historicalBranch}`} tone="good" />
        <Metric label="Bundles" value={String(deep.storage.bundleCount)} detail={`${deep.storage.fileCount} fichiers · ${deep.storage.capacityStatus}`} />
        <Metric label="Features joueurs" value={deep.playerReadiness.status.replaceAll("_", " ")} detail={deep.playerReadiness.temporality} tone="warning" />
        <Metric label="Cockpit privé" value={deep.deployment.private.replaceAll("_", " ")} detail={`v${deep.deployment.deploymentVersion ?? "—"} · ${deep.deployment.deploymentTime ?? "jamais"}`} tone="warning" />
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
        <Metric label="Matérialisées restantes" value={String(deep.progress.materializedTasksRemaining ?? 0)} detail={`${deep.progress.materializedCallsRemaining ?? 0} appels`} />
        <Metric label="Latentes fixtures" value={String(deep.progress.latentFixtureTasks ?? 0)} detail="enfants non matérialisés" />
        <Metric label="Latentes équipes" value={String(deep.progress.latentTeamTasks ?? 0)} detail="enfants non matérialisés" />
        <Metric label="Pages joueurs latentes" value={String(deep.progress.latentPlayerPages ?? 0)} detail="pagination estimée" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Forecast complet</span><h2>Bas, central et haut</h2></div><StatusPill value="MATERIALIZED_PLUS_LATENT" /></div>
        <div className="table-wrap"><table><thead><tr><th>Scénario</th><th>Appels</th><th>ETA A</th><th>ETA B</th><th>ETA globale</th><th>Stockage projeté</th></tr></thead><tbody>
          {(["low", "base", "high"] as const).map((scenario) => <tr key={scenario}><td>{scenario.toUpperCase()}</td><td>{deep.progress[scenario === "low" ? "callsRemainingLow" : scenario === "base" ? "callsRemainingBase" : "callsRemainingHigh"]}</td><td>{deep.progress.etaPriorityA[scenario]} j</td><td>{deep.progress.etaPriorityB[scenario]} j</td><td>{deep.progress.etaFull[scenario]} j</td><td>{((deep.storage[scenario === "low" ? "projectedBytesLow" : scenario === "base" ? "projectedBytesBase" : "projectedBytesHigh"] ?? 0) / 1_048_576).toFixed(1)} MiB</td></tr>)}
        </tbody></table></div>
        <p className="muted">{deep.progress.materializedEtaLabel} : {deep.progress.materializedEtaDays ?? "—"} jour. Cette valeur n’est pas l’ETA complète.</p>
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

type GateRow = {
  name?: string;
  status: string;
  passed: boolean;
  eligible_seasons?: number[];
  reason?: string;
};

type DatasetRow = {
  name?: string;
  version?: string;
  rows?: number;
  fixtures?: number;
  coverage?: number;
  quality?: string;
  temporalPolicy?: string;
  status?: string;
  sha256?: string;
};

function jalon6Snapshot() {
  return snapshot.deepData as typeof snapshot.deepData & {
    datasetReadiness?: {
      status?: string;
      gates?: Record<string, GateRow>;
      seasons?: Array<{
        season: number;
        canonical_fixtures: number;
        fixtures_expected: number;
        results_coverage: number;
        status: string;
      }>;
    };
    datasets?: DatasetRow[];
    strategies?: Array<{
      strategy_version?: string;
      strategy?: string;
      market?: string;
      bets?: number;
      roi?: number | null;
      max_drawdown_units?: number;
      confidence_interval_per_bet?: Array<number | null>;
      adjusted_p_value?: number | null;
      status?: string;
    }>;
  };
}

function DatasetReadiness() {
  const deep = jalon6Snapshot();
  const readiness = deep.datasetReadiness;
  const gates = Object.entries(readiness?.gates ?? {});
  const seasons = readiness?.seasons ?? [];
  return (
    <>
      <section className="metrics-grid">
        {gates.map(([name, gate]) => <Metric key={name} label={`Gate ${name}`} value={gate.status.replaceAll("_", " ")} detail={(gate.eligible_seasons ?? []).join(" · ") || gate.reason || "aucune saison"} tone={gate.passed ? "good" : "warning"} />)}
        <Metric label="Production" value="PRODUCTION_LOCKED" detail="aucune promotion réelle" tone="warning" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Audit Ligue 1 2018–2025</span><h2>Couverture canonique multi-saison</h2></div><StatusPill value={readiness?.status ?? "NO_OUTPUT"} /></div>
        {seasons.length ? <div className="table-wrap"><table><thead><tr><th>Saison</th><th>Fixtures</th><th>Attendues</th><th>Résultats</th><th>Statut</th></tr></thead><tbody>
          {seasons.map((season) => <tr key={season.season}><td>{season.season}</td><td>{season.canonical_fixtures}</td><td>{season.fixtures_expected}</td><td>{pct(season.results_coverage)}</td><td><StatusPill value={season.status} /></td></tr>)}
        </tbody></table></div> : <EmptyState title="Readiness en attente" text="Le prochain workflow qualité publiera les gates sans appel fournisseur." label="NO OUTPUT" />}
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Manifests versionnés</span><h2>Datasets disponibles</h2></div><SourceBadge origin="HISTORICAL POINT-IN-TIME" /></div>
        {deep.datasets?.length ? <div className="table-wrap"><table><thead><tr><th>Dataset</th><th>Lignes</th><th>Fixtures</th><th>Temporalité</th><th>Statut</th><th>Hash</th></tr></thead><tbody>
          {deep.datasets.map((dataset) => <tr key={dataset.version}><td>{dataset.name}</td><td>{dataset.rows ?? "—"}</td><td>{dataset.fixtures ?? "—"}</td><td>{dataset.temporalPolicy ?? "—"}</td><td><StatusPill value={dataset.status ?? "NO_OUTPUT"} /></td><td><code>{dataset.sha256?.slice(0, 12) ?? "—"}</code></td></tr>)}
        </tbody></table></div> : <EmptyState title="Datasets en attente" text="Aucun dataset incomplet n'est publié silencieusement." label="NO OUTPUT" />}
      </section>
    </>
  );
}

function LineupExplorer() {
  const deep = jalon6Snapshot();
  const expected = deep.datasets?.find((item) => item.name === "api_player_pre_lineup_v1");
  const confirmed = deep.datasets?.find((item) => item.name === "api_post_lineup_simulated_v1");
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Deux temporalités incompatibles</span><h2>Onze attendu et onze confirmé simulé</h2></div><StatusPill value={confirmed?.status ?? "BLOCKED_BY_COVERAGE"} /></div>
      <div className="cost-grid">
        <article><SourceBadge origin="HISTORICAL POINT-IN-TIME" /><strong>{expected?.fixtures ?? 0} fixtures</strong><small>PRE_LINEUP · historique antérieur uniquement</small></article>
        <article><SourceBadge origin="HISTORICAL SIMULATED" /><strong>{confirmed?.fixtures ?? 0} fixtures</strong><small>POST_LINEUP_SIMULATED · composition cible autorisée</small></article>
        <article><SourceBadge origin="NO OUTPUT" /><strong>0 mélange</strong><small>La composition cible ne peut jamais entrer dans PRE_LINEUP</small></article>
      </div>
    </section>
  );
}

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
      <div className="panel-head"><div><span>Readiness joueurs</span><h2>Garde-fous par famille</h2></div><StatusPill value={snapshot.deepData.playerReadiness.status} /></div>
      <div className="table-wrap"><table><thead><tr><th>Famille</th><th>Comp.</th><th>Saisons</th><th>Équipes</th><th>Fixtures</th><th>Joueurs</th><th>Null</th><th>Qualité</th><th>Temporalité</th><th>Statut</th><th>Blocage</th></tr></thead><tbody>
        {snapshot.deepData.playerReadiness.families.map((family) => <tr key={family.name}><td>{family.name}</td><td>{family.coverage.competitionCount}</td><td>{family.coverage.seasonCount}</td><td>{family.coverage.teamCount}</td><td>{family.coverage.fixtureCount}</td><td>{family.coverage.playerCount}</td><td>{family.coverage.nullRate == null ? "—" : `${(family.coverage.nullRate * 100).toFixed(1)} %`}</td><td>{family.quality}</td><td>{family.temporality}</td><td><StatusPill value={family.status} /></td><td>{family.reason}</td></tr>)}
      </tbody></table></div>
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
  const models = snapshot.deepData.models as Array<{
    name: string;
    version: string;
    dataset?: string;
    calibration?: string;
    logLoss: number | null;
    brier: number | null;
    ece?: number | null;
    status: string;
    origin: string;
  }>;
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Comparaison probabiliste</span><h2>Modèles et couverture</h2></div><StatusPill value="PRODUCTION_LOCKED" /></div>
      <div className="table-wrap"><table><thead><tr><th>Modèle</th><th>Dataset</th><th>Calibration</th><th>Log Loss OOS</th><th>Brier OOS</th><th>ECE</th><th>Statut</th><th>Origine</th></tr></thead><tbody>
        {models.map((model) => <tr key={model.name}><td>{model.name}</td><td>{model.dataset ?? "—"}</td><td>{model.calibration ?? "—"}</td><td>{model.logLoss == null ? "—" : model.logLoss.toFixed(4)}</td><td>{model.brier == null ? "—" : model.brier.toFixed(4)}</td><td>{model.ece == null ? "—" : model.ece.toFixed(4)}</td><td><StatusPill value={model.status} /></td><td><SourceBadge origin={model.origin} /></td></tr>)}
      </tbody></table></div>
    </section>
  );
}

function ModelArena() {
  type ArenaComparison = {
    comparison_id?: string;
    paired_fixtures?: number;
    paired_log_loss_delta?: number;
    paired_brier_delta?: number;
    decision?: string;
    status?: string;
    performance_by_season?: Record<string, { fixtures?: number; log_loss_delta?: number }>;
    uncertainty?: {
      ci90?: number[];
      ci95?: number[];
      probability_challenger_better?: number;
    };
  };
  type LeaderboardRow = {
    model: string;
    dataset?: string;
    sample?: number;
    paired_sample?: number;
    calibration?: string;
    metrics?: { log_loss?: number; brier_score?: number; ece?: number };
    reliability_curve?: Array<{ mean_confidence?: number | null; accuracy?: number | null }>;
    status?: string;
  };
  const arena = (snapshot.deepData as unknown as {
    modelArena?: {
      status?: string;
      baselineStatus?: string;
      externalProtocol?: string;
      modelsTested?: number;
      predictions?: number;
      comparisons?: ArenaComparison[];
      leaderboard?: LeaderboardRow[];
      calibrationAudits?: Record<string, { method?: string; leakage_guard?: string; evaluation_labels_used_for_selection?: number }>;
      featureStability?: Array<{ feature?: string; missing_rate?: number | null; direction_stable?: boolean; status?: string }>;
      scoreModels?: Array<{ model?: string; fixtures?: number; mean_home_goals?: number; mean_away_goals?: number; markets?: string[]; status?: string }>;
      oosGovernance?: Array<{ period?: string; seasons?: string }>;
      strategyStatus?: string;
      strategiesTested?: number;
      liveCandidates?: number;
      providerCalls?: number;
      quotaConsumed?: number;
      productionStatus?: string;
    };
  }).modelArena;
  const comparisons = arena?.comparisons ?? [];
  const leaderboard = arena?.leaderboard ?? [];
  const [challenger, setChallenger] = useState(leaderboard[0]?.model ?? "");
  const [reference, setReference] = useState(leaderboard[1]?.model ?? "");
  const selectedComparison = comparisons.find((row) => {
    const id = row.comparison_id ?? "";
    return id.includes(challenger) && id.includes(reference);
  }) ?? comparisons[0];
  const selectedModel = leaderboard.find((row) => row.model === challenger);
  const reliabilityPoints = (selectedModel?.reliability_curve ?? [])
    .filter((point) => point.mean_confidence != null && point.accuracy != null)
    .map((point) => `${Number(point.mean_confidence) * 100},${100 - Number(point.accuracy) * 100}`)
    .join(" ");
  return (
    <>
      <section className="metrics-grid">
        <Metric label="Baseline" value={arena?.baselineStatus ?? "NOT FROZEN"} detail={arena?.externalProtocol ?? "protocol pending"} />
        <Metric label="Modèles testés" value={String(arena?.modelsTested ?? 0)} detail={`${arena?.predictions ?? 0} prédictions`} />
        <Metric label="Appels fournisseur" value={String(arena?.providerCalls ?? 0)} detail={`${arena?.quotaConsumed ?? 0} crédit consommé`} />
        <Metric label="Candidats live" value={String(arena?.liveCandidates ?? 0)} detail={arena?.productionStatus ?? "PRODUCTION_LOCKED"} />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Model Leaderboard</span><h2>Échantillons complets et appariés</h2></div><StatusPill value={arena?.status ?? "NOT_RUN"} /></div>
        {leaderboard.length ? <div className="table-wrap"><table><thead><tr><th>Modèle</th><th>Dataset</th><th>Complet</th><th>Apparié</th><th>Log Loss</th><th>Brier</th><th>ECE</th><th>Calibration</th><th>Statut</th></tr></thead><tbody>
          {leaderboard.map((row) => <tr key={row.model}><td>{row.model}</td><td>{row.dataset ?? "—"}</td><td>{row.sample ?? 0}</td><td>{row.paired_sample ?? 0}</td><td>{row.metrics?.log_loss?.toFixed(4) ?? "—"}</td><td>{row.metrics?.brier_score?.toFixed(4) ?? "—"}</td><td>{row.metrics?.ece?.toFixed(4) ?? "—"}</td><td>{row.calibration ?? "NONE"}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
        </tbody></table></div> : <EmptyState title="Arène en attente" text="Aucun résultat n'est inventé avant l'exécution reproductible sur historical-data." label="NO OUTPUT" />}
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Head-to-Head · exact fixtures</span><h2>Comparaison appariée interactive</h2></div><StatusPill value={selectedComparison?.status ?? "INCONCLUSIVE"} /></div>
        <div className="explorer-tools">
          <label>Challenger<select value={challenger} onChange={(event) => setChallenger(event.target.value)}>{leaderboard.map((row) => <option key={row.model}>{row.model}</option>)}</select></label>
          <label>Référence<select value={reference} onChange={(event) => setReference(event.target.value)}>{leaderboard.map((row) => <option key={row.model}>{row.model}</option>)}</select></label>
        </div>
        {selectedComparison ? <div className="cost-grid">
          <article><span>Fixtures communes</span><strong>{selectedComparison.paired_fixtures ?? 0}</strong><small>{selectedComparison.comparison_id}</small></article>
          <article><span>Δ Log Loss</span><strong>{selectedComparison.paired_log_loss_delta?.toFixed(4) ?? "—"}</strong><small>Δ Brier {selectedComparison.paired_brier_delta?.toFixed(4) ?? "—"}</small></article>
          <article><span>CI 90 %</span><strong>{selectedComparison.uncertainty?.ci90?.map((value) => value.toFixed(4)).join(" · ") ?? "—"}</strong><small>CI 95 % {selectedComparison.uncertainty?.ci95?.map((value) => value.toFixed(4)).join(" · ") ?? "—"}</small></article>
          <article><span>P(supériorité)</span><strong>{selectedComparison.uncertainty?.probability_challenger_better == null ? "—" : pct(selectedComparison.uncertainty.probability_challenger_better)}</strong><small>{selectedComparison.decision ?? "INCONCLUSIVE"}</small></article>
        </div> : <EmptyState title="Paire non préenregistrée" text="Une paire absente n'est jamais comparée indirectement." label="NO PAIRED OUTPUT" />}
        {selectedComparison?.performance_by_season && <div className="table-wrap"><table><thead><tr><th>Saison</th><th>Fixtures</th><th>Δ Log Loss</th></tr></thead><tbody>{Object.entries(selectedComparison.performance_by_season).map(([season, row]) => <tr key={season}><td>{season}</td><td>{row.fixtures ?? 0}</td><td>{row.log_loss_delta?.toFixed(4) ?? "—"}</td></tr>)}</tbody></table></div>}
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Calibration Lab</span><h2>Courbe de fiabilité cross-fitted</h2></div><StatusPill value="CROSS_FITTED_CALIBRATION_READY" /></div>
        <svg viewBox="0 0 100 100" role="img" aria-label={`Courbe de fiabilité ${challenger}`} style={{ width: "100%", maxWidth: 420, height: 220 }}>
          <line x1="0" y1="100" x2="100" y2="0" stroke="currentColor" strokeDasharray="4 4" />
          {reliabilityPoints && <polyline points={reliabilityPoints} fill="none" stroke="#35d6a5" strokeWidth="2" />}
        </svg>
        <div className="table-wrap"><table><thead><tr><th>Modèle</th><th>Sélection</th><th>Garde anti-fuite</th><th>Labels OOS utilisés</th></tr></thead><tbody>
          {Object.entries(arena?.calibrationAudits ?? {}).map(([name, audit]) => <tr key={name}><td>{name}</td><td>{audit.method ?? "NONE"}</td><td>{audit.leakage_guard ?? "FIXED_BASELINE"}</td><td>{audit.evaluation_labels_used_for_selection ?? 0}</td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Feature Ablation</span><h2>Blocs retirés et stabilité</h2></div><StatusPill value="PLAYER_INCREMENTAL_VALUE_INCONCLUSIVE" /></div>
        <div className="table-wrap"><table><thead><tr><th>Feature</th><th>Null</th><th>Direction stable</th><th>Statut</th></tr></thead><tbody>{(arena?.featureStability ?? []).map((row) => <tr key={row.feature}><td>{row.feature}</td><td>{row.missing_rate == null ? "—" : pct(row.missing_rate)}</td><td>{row.direction_stable ? "oui" : "non"}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}</tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Score Models</span><h2>Poisson · Dixon–Coles</h2></div><StatusPill value="SCORE_MODEL_READY" /></div>
        <div className="table-wrap"><table><thead><tr><th>Modèle</th><th>Fixtures</th><th>Buts dom.</th><th>Buts ext.</th><th>Marchés</th><th>Statut</th></tr></thead><tbody>{(arena?.scoreModels ?? []).map((row) => <tr key={row.model}><td>{row.model}</td><td>{row.fixtures ?? 0}</td><td>{row.mean_home_goals?.toFixed(3) ?? "—"}</td><td>{row.mean_away_goals?.toFixed(3) ?? "—"}</td><td>{row.markets?.join(" · ")}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}</tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>OOS Governance</span><h2>Périodes irréversibles</h2></div><StatusPill value="PRODUCTION_LOCKED" /></div>
        <div className="cost-grid">{(arena?.oosGovernance ?? []).map((row) => <article key={row.period}><span>{row.period}</span><strong>{row.seasons}</strong><small>usage gouverné</small></article>)}</div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Stratégies bornées</span><h2>Strategy Lab V2</h2></div><StatusPill value={arena?.strategyStatus ?? "NOT_RUN"} /></div>
        <p>{arena?.strategiesTested ?? 0} hypothèses exécutées. Aucune stratégie n&apos;est promue sans intervalle apparié favorable, validation externe et confirmation prospective indépendante.</p>
      </section>
    </>
  );
}

function ExternalValidation() {
  type MetricBundle = {
    matches?: number;
    log_loss?: number;
    brier_score?: number;
    ece?: number;
    accuracy?: number;
    status?: string;
  };
  type ExternalGate = {
    status?: string;
    fixtures?: number;
    coverage?: number;
  };
  type ReadinessRow = {
    competition: string;
    seasons?: Array<{ season?: number; fixtures_canonical?: number; status?: string }>;
    teams?: number;
    players?: number;
    gates?: Record<string, ExternalGate>;
  };
  type ComparisonRow = {
    comparison_id?: string;
    paired_fixtures?: number;
    paired_log_loss_delta?: number;
    uncertainty?: { ci95?: number[]; probability_challenger_better?: number };
    status?: string;
    reason?: string;
  };
  type LoloRow = {
    held_out_competition?: string;
    paired_fixtures?: number;
    metrics?: MetricBundle;
    market_comparison?: string;
    status?: string;
  };
  const external = (snapshot.deepData as unknown as {
    externalValidation?: {
      status?: string;
      protocol?: { status?: string; hash?: string; frozen_at?: string };
      readiness?: ReadinessRow[];
      datasets?: Array<{
        name?: string;
        competition?: string;
        seasons?: number[];
        fixtures?: number;
        rows?: number;
        status?: string;
      }>;
      models?: Record<string, { status?: string; predictions?: number; metrics?: MetricBundle }>;
      comparisons?: ComparisonRow[];
      leaveOneLeagueOut?: LoloRow[];
      playerGeneralization?: Array<{ competition?: string; status?: string; reason?: string }>;
      strategies?: {
        status?: string;
        hypotheses?: number;
        backtests?: number;
        live_shadow_candidates?: number;
      };
      package?: {
        package?: string;
        status?: string;
        NO_BET_DEFAULT?: boolean;
        REAL_BETS?: boolean;
        PRODUCTION_LOCKED?: boolean;
        package_hash?: string;
      };
      predictions?: number;
      providerCalls?: number;
      quotaConsumed?: number;
      productionStatus?: string;
    };
  }).externalValidation;
  const readiness = external?.readiness ?? [];
  const models = Object.entries(external?.models ?? {});
  const comparisons = external?.comparisons ?? [];
  return (
    <>
      <section className="metrics-grid">
        <Metric label="Protocole externe" value={external?.protocol?.status ?? "NOT_LOCKED"} detail={(external?.protocol?.hash ?? "—").slice(0, 16)} />
        <Metric label="Prédictions" value={String(external?.predictions ?? 0)} detail="cache durable uniquement" />
        <Metric label="Appels fournisseur" value={String(external?.providerCalls ?? 0)} detail={`${external?.quotaConsumed ?? 0} crédit consommé`} />
        <Metric label="Package pré-saison" value={external?.package?.status ?? "WAITING"} detail={external?.package?.NO_BET_DEFAULT ? "NO_BET_DEFAULT" : "non gelé"} />
        <Metric label="Production" value={external?.productionStatus ?? "PRODUCTION_LOCKED"} detail="REAL_BETS = false" tone="warning" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>External Readiness</span><h2>Gates par compétition</h2></div><StatusPill value={external?.status ?? "WAITING_FOR_EXTERNAL_GATES"} /></div>
        <div className="table-wrap"><table><thead><tr><th>Compétition</th><th>Saisons</th><th>Fixtures</th><th>Équipes</th><th>Joueurs roster</th><th>TEAM</th><th>PLAYER</th><th>LINEUP</th><th>MARKET</th><th>EXTERNAL</th></tr></thead><tbody>
          {readiness.map((row) => <tr key={row.competition}><td>{row.competition}</td><td>{row.seasons?.length ?? 0}</td><td>{row.gates?.TEAM_GATE?.fixtures ?? 0}</td><td>{row.teams ?? 0}</td><td>{row.players ?? 0}</td><td><StatusPill value={row.gates?.TEAM_GATE?.status ?? "UNAVAILABLE"} /></td><td><StatusPill value={row.gates?.PLAYER_GATE?.status ?? "UNAVAILABLE"} /></td><td><StatusPill value={row.gates?.LINEUP_GATE?.status ?? "UNAVAILABLE"} /></td><td><StatusPill value={row.gates?.MARKET_GATE?.status ?? "UNAVAILABLE"} /></td><td><StatusPill value={row.gates?.EXTERNAL_VALIDATION_GATE?.status ?? "UNAVAILABLE"} /></td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>League Transfer Matrix</span><h2>Transfert · spécifique · pooled · score</h2></div><StatusPill value="NO_RETUNING" /></div>
        <div className="table-wrap"><table><thead><tr><th>Famille</th><th>Prédictions</th><th>Log Loss</th><th>Brier</th><th>ECE</th><th>Accuracy</th><th>Statut</th></tr></thead><tbody>
          {models.map(([name, row]) => <tr key={name}><td>{name.replaceAll("_", " ")}</td><td>{row.predictions ?? 0}</td><td>{row.metrics?.log_loss?.toFixed(4) ?? "—"}</td><td>{row.metrics?.brier_score?.toFixed(4) ?? "—"}</td><td>{row.metrics?.ece?.toFixed(4) ?? "—"}</td><td>{row.metrics?.accuracy == null ? "—" : pct(row.metrics.accuracy)}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Leave-One-League-Out</span><h2>Généralisation football</h2></div><StatusPill value="LEAVE_ONE_LEAGUE_OUT_READY" /></div>
        <div className="table-wrap"><table><thead><tr><th>Ligue tenue à l&apos;écart</th><th>Fixtures</th><th>Log Loss</th><th>Brier</th><th>ECE</th><th>Marché</th><th>Statut</th></tr></thead><tbody>
          {(external?.leaveOneLeagueOut ?? []).map((row) => <tr key={row.held_out_competition}><td>{row.held_out_competition}</td><td>{row.paired_fixtures ?? 0}</td><td>{row.metrics?.log_loss?.toFixed(4) ?? "—"}</td><td>{row.metrics?.brier_score?.toFixed(4) ?? "—"}</td><td>{row.metrics?.ece?.toFixed(4) ?? "—"}</td><td>{row.market_comparison ?? "UNAVAILABLE"}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Player Generalization</span><h2>Valeur incrémentale par ligue</h2></div><StatusPill value="PLAYER_GENERALIZATION_INCONCLUSIVE" /></div>
        <div className="table-wrap"><table><thead><tr><th>Compétition</th><th>Statut</th><th>Raison factuelle</th></tr></thead><tbody>
          {(external?.playerGeneralization ?? []).map((row) => <tr key={row.competition}><td>{row.competition}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td><td>{row.reason ?? "—"}</td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Strategy External Validation</span><h2>Comparaisons appariées et marché</h2></div><StatusPill value={external?.strategies?.status ?? "NO_EXTERNAL_VALIDATED_EDGE"} /></div>
        <div className="table-wrap"><table><thead><tr><th>Comparaison</th><th>Fixtures appariées</th><th>Δ Log Loss</th><th>CI 95 %</th><th>P supériorité</th><th>Statut</th></tr></thead><tbody>
          {comparisons.map((row) => <tr key={row.comparison_id}><td>{row.comparison_id}</td><td>{row.paired_fixtures ?? 0}</td><td>{row.paired_log_loss_delta?.toFixed(4) ?? "—"}</td><td>{row.uncertainty?.ci95?.map((value) => value.toFixed(4)).join(" · ") ?? row.reason ?? "—"}</td><td>{row.uncertainty?.probability_challenger_better == null ? "—" : pct(row.uncertainty.probability_challenger_better)}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Preseason Package</span><h2>{external?.package?.package ?? "PRESEASON_SHADOW_PACKAGE_V1"}</h2></div><StatusPill value={external?.package?.status ?? "WAITING"} /></div>
        <div className="cost-grid">
          <article><span>NO_BET_DEFAULT</span><strong>{external?.package?.NO_BET_DEFAULT ? "true" : "false"}</strong><small>politique par défaut</small></article>
          <article><span>REAL_BETS</span><strong>{external?.package?.REAL_BETS ? "true" : "false"}</strong><small>reste désactivé</small></article>
          <article><span>PRODUCTION_LOCKED</span><strong>{external?.package?.PRODUCTION_LOCKED ? "true" : "false"}</strong><small>aucune promotion</small></article>
          <article><span>Hash</span><strong>{(external?.package?.package_hash ?? "—").slice(0, 16)}</strong><small>package versionné</small></article>
        </div>
      </section>
    </>
  );
}

function HistoricalStrategyLab() {
  const rows = jalon6Snapshot().strategies ?? [];
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Bonferroni · sensibilité des seuils</span><h2>Stratégies historiques candidates</h2></div><StatusPill value="NO_PROMOTION" /></div>
      {rows.length ? <div className="table-wrap"><table><thead><tr><th>Hypothèse</th><th>Marché</th><th>Paris</th><th>ROI</th><th>Drawdown</th><th>p ajustée</th><th>Statut</th></tr></thead><tbody>
        {rows.map((row) => <tr key={row.strategy_version ?? row.strategy}><td>{row.strategy_version ?? row.strategy}</td><td>{row.market}</td><td>{row.bets ?? 0}</td><td>{row.roi == null ? "—" : pct(row.roi)}</td><td>{row.max_drawdown_units?.toFixed(2) ?? "—"} u</td><td>{row.adjusted_p_value?.toFixed(4) ?? "—"}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
      </tbody></table></div> : <EmptyState title="Strategy Lab en attente" text="Aucune stratégie n'est promue sans OOS, volume et robustesse." label="NO OUTPUT" />}
    </section>
  );
}

function CriticalClosure() {
  type Gate = {
    competition?: string;
    status?: string;
    one_x_two_status?: string;
    totals_status?: string;
    coverage?: number;
    mapping_rate?: number;
    fixtures_mapped?: number;
    ambiguities?: number;
  };
  const closure = (snapshot.deepData as unknown as {
    criticalClosure?: {
      status?: string;
      teamGates?: Record<string, { status?: string; coverage?: number }>;
      playerGates?: Gate[];
      lineupGates?: Gate[];
      marketGates?: Gate[];
      matching?: { matched?: number; market_rows?: number; mapping_rate?: number; ambiguous?: number };
      files?: number;
      marketRows?: number;
      storage?: {
        actual_bytes?: number;
        critical_gates_only?: number;
        current_full_plan?: number;
        current_full_plan_plus_market?: number;
        status?: string;
      };
      r2?: { mode?: string; uploaded?: number; deletions?: number };
      strategy?: { status?: string; live_shadow_candidates?: number; shadow_model_candidates?: number };
      marketValidation?: {
        status?: string;
        paired_predictions?: number;
        comparisons?: Array<{
          competition?: string;
          model?: string;
          paired_fixtures?: number;
          model_log_loss?: number;
          market_log_loss?: number;
          paired_log_loss_delta?: number;
          ci95?: number[];
          status?: string;
        }>;
      };
      package?: { status?: string; NO_BET_DEFAULT?: boolean };
      oddsApi?: { credits_consumed?: number; estimated_credits?: number };
      productionStatus?: string;
      realBets?: boolean;
    };
  }).criticalClosure;
  const bytes = (value?: number) => value == null ? "—" : `${(value / 1_000_000).toFixed(1)} MB`;
  const gateRows = [
    ...(closure?.marketGates ?? []).map((gate) => ({ ...gate, family: "MARKET" })),
    ...(closure?.playerGates ?? []).map((gate) => ({ ...gate, family: "PLAYER" })),
    ...(closure?.lineupGates ?? []).map((gate) => ({ ...gate, family: "LINEUP" })),
  ];
  return (
    <>
      <section className="metrics-grid">
        <Metric label="Fichiers Football-Data" value={String(closure?.files ?? 0)} detail={`${closure?.marketRows ?? 0} lignes marché`} />
        <Metric label="Matching fixture" value={`${(((closure?.matching?.mapping_rate ?? 0) * 100)).toFixed(1)} %`} detail={`${closure?.matching?.matched ?? 0}/${closure?.matching?.market_rows ?? 0} · ${closure?.matching?.ambiguous ?? 0} ambiguïté`} />
        <Metric label="The Odds API historique" value={`${closure?.oddsApi?.credits_consumed ?? 0} crédit`} detail={`dry-run ${closure?.oddsApi?.estimated_credits ?? 0}`} />
        <Metric label="Object storage" value={closure?.storage?.status ?? "OBJECT_STORAGE_OPTIONAL"} detail={`R2 ${closure?.r2?.mode ?? "WAITING"}`} />
        <Metric label="Production" value={closure?.productionStatus ?? "PRODUCTION_LOCKED"} detail="REAL_BETS = false" tone="warning" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Critical Gate Monitor</span><h2>Gates par ligue et famille</h2></div><StatusPill value={closure?.status ?? "JALON_9_WAITING"} /></div>
        <div className="table-wrap"><table><thead><tr><th>Famille</th><th>Compétition</th><th>Statut</th><th>Coverage</th><th>Mapping</th><th>1X2</th><th>Totals</th></tr></thead><tbody>
          {gateRows.map((gate, index) => <tr key={`${gate.family}-${gate.competition}-${index}`}><td>{gate.family}</td><td>{gate.competition}</td><td><StatusPill value={gate.status ?? "UNAVAILABLE"} /></td><td>{gate.coverage == null ? "—" : pct(gate.coverage)}</td><td>{gate.mapping_rate == null ? "—" : pct(gate.mapping_rate)}</td><td>{gate.one_x_two_status ?? "—"}</td><td>{gate.totals_status ?? "—"}</td></tr>)}
        </tbody></table></div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Storage Control Center</span><h2>Capacité et projections</h2></div><StatusPill value={closure?.storage?.status ?? "OBJECT_STORAGE_OPTIONAL"} /></div>
        <div className="cost-grid">
          <article><span>Actuel</span><strong>{bytes(closure?.storage?.actual_bytes)}</strong><small>historical-data</small></article>
          <article><span>Gates critiques</span><strong>{bytes(closure?.storage?.critical_gates_only)}</strong><small>projection ciblée</small></article>
          <article><span>Plan complet</span><strong>{bytes(closure?.storage?.current_full_plan)}</strong><small>projection centrale</small></article>
          <article><span>Plan + marché</span><strong>{bytes(closure?.storage?.current_full_plan_plus_market)}</strong><small>projection haute</small></article>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Market Model Arena</span><h2>Validation et package pré-saison V2</h2></div><StatusPill value={closure?.strategy?.status ?? "NO_EXTERNAL_VALIDATED_EDGE"} /></div>
        <div className="cost-grid">
          <article><span>Stratégies shadow</span><strong>{closure?.strategy?.live_shadow_candidates ?? 0}</strong><small>aucune promotion automatique</small></article>
          <article><span>Modèles shadow</span><strong>{closure?.strategy?.shadow_model_candidates ?? 0}</strong><small>conditionnés par MARKET_GATE</small></article>
          <article><span>Package</span><strong>{closure?.package?.status ?? "WAITING"}</strong><small>{closure?.package?.NO_BET_DEFAULT ? "NO_BET_DEFAULT" : "gate en attente"}</small></article>
          <article><span>R2 suppressions</span><strong>{closure?.r2?.deletions ?? 0}</strong><small>interdites avant validation</small></article>
        </div>
        <div className="table-wrap"><table><thead><tr><th>Ligue</th><th>Modèle gelé</th><th>Fixtures</th><th>Log Loss modèle</th><th>Log Loss marché</th><th>Delta</th><th>IC 95 %</th><th>Statut</th></tr></thead><tbody>
          {(closure?.marketValidation?.comparisons ?? []).map((row, index) => <tr key={`${row.competition}-${row.model}-${index}`}><td>{row.competition}</td><td>{row.model}</td><td>{row.paired_fixtures ?? 0}</td><td>{row.model_log_loss?.toFixed(4) ?? "—"}</td><td>{row.market_log_loss?.toFixed(4) ?? "—"}</td><td>{row.paired_log_loss_delta?.toFixed(4) ?? "—"}</td><td>{row.ci95?.map((value) => value.toFixed(4)).join(" · ") ?? "—"}</td><td><StatusPill value={row.status ?? "INCONCLUSIVE"} /></td></tr>)}
        </tbody></table></div>
      </section>
    </>
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
