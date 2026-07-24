"use client";

import { useMemo, useState } from "react";
import snapshot from "./cockpit-data.json";

type PageKey =
  | "command"
  | "matches"
  | "odds"
  | "bets"
  | "quality"
  | "strategy";

const pages: { key: PageKey; label: string; glyph: string }[] = [
  { key: "command", label: "Command Center", glyph: "⌂" },
  { key: "matches", label: "Match Center", glyph: "◉" },
  { key: "odds", label: "Odds Monitor", glyph: "↗" },
  { key: "bets", label: "Shadow Bets", glyph: "◆" },
  { key: "quality", label: "Data Quality", glyph: "✓" },
  { key: "strategy", label: "Strategy Lab", glyph: "∿" },
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
    title: "Odds Monitor",
    note: "Snapshots append-only et fraîcheur par bookmaker.",
  },
  bets: {
    eyebrow: "Journal de décision",
    title: "Shadow Bets",
    note: "Chaque candidat et chaque rejet restent expliqués.",
  },
  quality: {
    eyebrow: "Contrôles & provenance",
    title: "Data Quality",
    note: "La qualité bloque la décision avant le modèle.",
  },
  strategy: {
    eyebrow: "Validation hors échantillon",
    title: "Strategy Lab",
    note: "Comparaisons OOS : aucune stratégie n’est promue.",
  },
};

function SourceBadge({ origin }: { origin: string }) {
  const token = origin.toLowerCase().replace(" source", "").replace(" data", "");
  return <span className={`source-badge ${token}`}>{origin}</span>;
}

function StatusPill({ value }: { value: string }) {
  const token = value.toLowerCase().replaceAll("_", "-");
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

export default function Home() {
  const [page, setPage] = useState<PageKey>("command");
  const [competition, setCompetition] = useState("Ligue 1");
  const [period, setPeriod] = useState("7 prochains jours");
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
          {page === "matches" && <MatchCenter matches={filteredMatches} market={market} />}
          {page === "odds" && <OddsMonitor />}
          {page === "bets" && <ShadowBets />}
          {page === "quality" && <DataQuality />}
          {page === "strategy" && <StrategyLab />}
        </div>
      </section>
    </main>
  );
}

function CommandCenter({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const best = snapshot.strategies.find((item) => item.strategy === "over_2_5_value");
  return (
    <>
      <section className="metric-grid">
        <Metric label="Fixtures suivies" value={String(snapshot.metrics.fixtures)} detail="fenêtre prospective" />
        <Metric label="Prédictions" value={String(snapshot.metrics.predictions)} detail="consensus Elo–Poisson" />
        <Metric label="Décisions acceptées" value={String(snapshot.metrics.candidates)} detail="aucune mise réelle" />
        <Metric label="Rejets explicites" value={String(snapshot.metrics.rejections)} detail="motif normalisé" tone="amber" />
        <Metric label="Couverture legacy" value={`${snapshot.metrics.migrationCoveragePct} %`} detail="mapping certain" tone="cyan" />
        <Metric label="P&L shadow" value="0,00 u" detail="ROI 0,00 % · DD 0,00 u" />
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
                <div><strong>{run.pipeline}</strong><small>{dateTime(run.finishedAt)}</small></div>
                <SourceBadge origin={run.origin} />
                <StatusPill value={run.status} />
              </div>
            ))}
          </div>
        </article>

        <article className="panel insight">
          <div className="panel-head">
            <div><span>Signal OOS le moins faible</span><h2>Over 2,5 · valeur</h2></div>
            <SourceBadge origin="LEGACY SOURCE" />
          </div>
          <strong className="big-roi">+{best?.roiPct.toFixed(2)} %</strong>
          <span>ROI observé · {best?.bets} paris historiques</span>
          <div className="ci"><b style={{ left: "19%", width: "64%" }} /><i style={{ left: "50%" }} /></div>
          <div className="ci-label"><span>{best?.ciLowPct} %</span><strong>IC 95 %</strong><span>+{best?.ciHighPct} %</span></div>
          <div className="warning">Intervalle compatible avec une perte. Résultat inconclusif, non promu.</div>
          <button className="text-button" onClick={() => onNavigate("strategy")}>Ouvrir Strategy Lab →</button>
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
            ["Collisions UUID", "PASS", "0 collision"],
            ["Quota mensuel", "PASS", "plafond 450"],
            ["Cotes réelles", "PENDING", "collecte à confirmer"],
          ].map(([name, status, detail]) => (
            <div key={name}><StatusPill value={status} /><strong>{name}</strong><small>{detail}</small></div>
          ))}
        </div>
      </section>
    </>
  );
}

function MatchCenter({ matches, market }: { matches: typeof snapshot.matches; market: string }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div><span>{matches.length} fixture affichée</span><h2>Probabilités pré-match · {market}</h2></div>
        <SourceBadge origin="DEMO DATA" />
      </div>
      {matches.length === 0 ? (
        <EmptyState title="Aucun match pour ces filtres" text="Modifiez le modèle ou le niveau de qualité." label="DEMO DATA" />
      ) : (
        <div className="match-list">
          {matches.map((match) => (
            <article className="match-card" key={match.id}>
              <div className="match-meta"><span>{match.competition}</span><strong>{dateTime(match.kickoff)}</strong><SourceBadge origin={match.origin} /></div>
              <div className="teams"><strong>{match.home}</strong><span>vs</span><strong>{match.away}</strong></div>
              <div className="probabilities">
                {[["1", match.probabilities.home], ["N", match.probabilities.draw], ["2", match.probabilities.away]].map(([label, value]) => (
                  <div key={String(label)}><span>{label}</span><strong>{pct(value as number | null)}</strong><i style={{ width: pct(value as number | null) }} /></div>
                ))}
              </div>
              <div className="match-foot">
                <span>xG {match.expectedGoals.home?.toFixed(2)} — {match.expectedGoals.away?.toFixed(2)}</span>
                <StatusPill value={match.quality} />
                <span>Décision : <b>{match.decision}</b></span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function OddsMonitor() {
  return (
    <section className="panel">
      <div className="panel-head"><div><span>Snapshots horodatés</span><h2>Marché 1X2 & Totaux</h2></div><StatusPill value="PENDING" /></div>
      <EmptyState
        label="DEMO DATA"
        title="Aucune cote réelle dans cet artefact"
        text="Le pipeline et le stockage append-only sont prêts. Cette vue restera vide jusqu’à la première collecte authentifiée ; aucune cote synthétique n’est présentée comme réelle."
      />
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
              <span>Cote<strong>—</strong></span>
              <span>Mise fictive<strong>{decision.suggested_stake.toFixed(1)} u</strong></span>
            </div>
            <div className="reject"><StatusPill value="REJETÉ" /><strong>{decision.primary_reason}</strong><span>{decision.secondary_reasons.join(" · ")}</span></div>
          </article>
        ))}
      </div>
    </section>
  );
}

function DataQuality() {
  return (
    <>
      <section className="quality-summary">
        <Metric label="Contrôles au vert" value={`${snapshot.qualityChecks.filter((item) => item.status === "PASS").length}/${snapshot.qualityChecks.length}`} detail="sur l’artefact disponible" tone="cyan" />
        <Metric label="Mappages legacy" value="37 024" detail="UUID déterministes" />
        <Metric label="Ambigus / non résolus" value="0" detail="aucun cas masqué" />
        <Metric label="Alertes critiques" value="0" detail="production verrouillée" />
      </section>
      <section className="panel">
        <div className="panel-head"><div><span>Contrats de données</span><h2>Contrôles bloquants</h2></div><SourceBadge origin="LEGACY SOURCE" /></div>
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
