"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { formatNumber, formatPercent } from "../../i18n";
import {
  competitionRankings,
  familyDisplayName,
  hypothesisCompetitions,
  hypothesisFamilies,
  hypothesisFunnel,
  hypothesisIntelligence,
  hypothesisProspectiveFreeze,
  hypothesisRankings,
  scientificStatusLabel,
  subfamilyDisplayName,
  type RankingEntry,
} from "../../lib/hypothesis-universe";
import { useViewMode } from "../common/view-mode";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  RankingCard,
  ScientificStatusBadge,
  TagChip,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

export type RankingsPageVariant = "classements" | "longue-traine" | "observations";

type EvidenceAxis = {
  cutoff: string | null;
  cutoffLabel: string | null;
  market: string | null;
  marketLabel: string | null;
  origin: string | null;
  originLabel: string | null;
};

type AxisOption = {
  label: string;
  value: string;
};

const machineByHypothesisId = new Map(
  hypothesisIntelligence.machineDiscoveries.map(
    (entry) => [entry.id, entry] as const,
  ),
);
const ownerByHypothesisId = new Map(
  hypothesisIntelligence.ownerHypotheses.map(
    (entry) => [entry.id, entry] as const,
  ),
);
const freezeByHypothesisId = new Map(
  hypothesisProspectiveFreeze.contracts.map((entry) => [
    entry.hypothesis_id,
    entry,
  ] as const),
);

function selectionLabel(selection: string) {
  const labels: Record<string, string> = {
    AWAY: "Victoire à l’extérieur",
    DRAW: "Match nul",
    HOME: "Victoire à domicile",
  };
  return labels[selection] ?? "Sélection documentée";
}

function marketLabel(market: string, selection: string) {
  if (market.startsWith("1X2")) {
    return `Résultat du match · ${selectionLabel(selection)}`;
  }
  return "Marché documenté";
}

function cutoffLabel(cutoff: string) {
  const labels: Record<string, string> = {
    "H-24": "Vingt-quatre heures avant le coup d’envoi",
    "H-2": "Deux heures avant le coup d’envoi",
    NEAR_KICKOFF: "Près du coup d’envoi",
    POST_LINEUP: "Après publication des compositions",
  };
  return labels[cutoff] ?? "Heure limite documentée";
}

function evidenceFor(entry: RankingEntry): EvidenceAxis {
  const machine = machineByHypothesisId.get(entry.hypothesis_id);
  const owner = ownerByHypothesisId.get(entry.hypothesis_id);
  const freeze = freezeByHypothesisId.get(entry.hypothesis_id);
  return {
    cutoff: freeze?.primary_price.cutoff_name ?? null,
    cutoffLabel: freeze
      ? cutoffLabel(freeze.primary_price.cutoff_name)
      : null,
    market: machine?.market ?? null,
    marketLabel: machine
      ? marketLabel(machine.market, machine.selection)
      : null,
    origin: machine?.origin ?? owner?.origin ?? null,
    originLabel: machine?.badge ?? owner?.badge ?? null,
  };
}

function axisOptions(
  entries: RankingEntry[],
  valueKey: "cutoff" | "market" | "origin",
  labelKey: "cutoffLabel" | "marketLabel" | "originLabel",
) {
  const options = new Map<string, string>();
  for (const entry of entries) {
    const evidence = evidenceFor(entry);
    const value = evidence[valueKey];
    const label = evidence[labelKey];
    if (value && label) options.set(value, label);
  }
  return [...options.entries()]
    .map<AxisOption>(([value, label]) => ({ label, value }))
    .sort((left, right) => left.label.localeCompare(right.label, "fr"));
}

function matchesEvidenceAxes(
  entry: RankingEntry,
  axes: { cutoff: string; market: string; origin: string },
) {
  const evidence = evidenceFor(entry);
  return (
    (axes.cutoff === "ALL" || evidence.cutoff === axes.cutoff) &&
    (axes.market === "ALL" || evidence.market === axes.market) &&
    (axes.origin === "ALL" || evidence.origin === axes.origin)
  );
}

function DiscoveryRankingCard({ entry }: { entry: RankingEntry }) {
  return (
    <article className="hu-ranking-card hu-ranking-card-discovery">
      <div className="hu-ranking-card-head">
        <span className="hu-rank">#{entry.rank}</span>
        <ScientificStatusBadge status={entry.status} />
      </div>
      <h3>{entry.hypothesis_id}</h3>
      <p>{entry.label_fr}</p>
      <p>
        Une piste à comprendre avant d’ouvrir ses mesures et ses limites.
      </p>
      <Link className="hu-text-link" href={`/hypotheses/${entry.hypothesis_id}`}>
        Comprendre cette piste <span aria-hidden="true">→</span>
      </Link>
    </article>
  );
}

function RankingScatter({ entries }: { entries: RankingEntry[] }) {
  const supported = entries.filter(
    (entry) =>
      entry.historical_support != null && entry.historical_roi != null,
  );
  const maxSupport = Math.max(
    ...supported.map((entry) => entry.historical_support ?? 0),
    1,
  );
  const roiValues = supported.map((entry) => entry.historical_roi ?? 0);
  const minRoi = Math.min(...roiValues, 0);
  const maxRoi = Math.max(...roiValues, 0.01);
  const roiRange = Math.max(maxRoi - minRoi, 0.01);

  return (
    <figure className="hu-scatter">
      <figcaption>
        <strong>Support contre résultat historique brut</strong>
        <span>
          Un point haut mais très à gauche peut être spectaculaire et fragile.
        </span>
      </figcaption>
      <div className="hu-scatter-plot">
        <span className="hu-y-label">Résultat historique brut</span>
        <span className="hu-x-label">Nombre de matchs observés</span>
        <i className="hu-axis-x" aria-hidden="true" />
        <i className="hu-axis-y" aria-hidden="true" />
        {supported.map((entry) => (
          <Link
            aria-label={`${entry.hypothesis_id}, ${formatNumber(entry.historical_support ?? 0)} matchs, ${formatPercent(entry.historical_roi)}`}
            className="hu-scatter-point"
            href={`/hypotheses/${entry.hypothesis_id}`}
            key={entry.hypothesis_id}
            style={{
              bottom: `${12 + (((entry.historical_roi ?? 0) - minRoi) / roiRange) * 70}%`,
              left: `${12 + ((entry.historical_support ?? 0) / maxSupport) * 76}%`,
            }}
          >
            <span>{entry.rank}</span>
            <em>{entry.hypothesis_id}</em>
          </Link>
        ))}
      </div>
      <p className="hu-chart-summary">
        Résumé : {supported.length} signal{supported.length > 1 ? "aux" : ""}{" "}
        dispose{supported.length > 1 ? "nt" : ""} d’un support et d’un résultat
        historique publiés. Aucun n’est une stratégie validée.
      </p>
    </figure>
  );
}

function FalsePositiveChart({ entries }: { entries: RankingEntry[] }) {
  return (
    <figure className="hu-risk-chart">
      <figcaption>
        <strong>Résultat brut et risque de faux positif</strong>
        <span>
          La correction statistique peut invalider un résultat historique
          positif.
        </span>
      </figcaption>
      <div>
        {entries.map((entry) => (
          <article key={entry.hypothesis_id}>
            <div>
              <strong>{entry.hypothesis_id}</strong>
              <span>{formatPercent(entry.historical_roi)}</span>
            </div>
            <span className="hu-risk-track">
              {entry.q_value == null ? (
                <i aria-hidden="true" className="unavailable" />
              ) : (
                <i
                  aria-hidden="true"
                  style={{
                    width: `${Math.min(100, entry.q_value * 100)}%`,
                  }}
                />
              )}
            </span>
            <small>
              Risque de faux positif après correction :{" "}
              {entry.q_value == null
                ? "non disponible"
                : formatNumber(entry.q_value, 2)}
            </small>
          </article>
        ))}
      </div>
      <p className="hu-chart-summary">
        Cette valeur ajustée contrôle le taux attendu de fausses découvertes
        dans un ensemble de tests ; ce n’est pas la probabilité individuelle
        qu’une hypothèse soit fausse. Une valeur de 1 ne franchit pas le seuil
        de validation.
      </p>
    </figure>
  );
}

function CompetitionMatrix() {
  const representedFamilies = Array.from(
    new Set(
      hypothesisRankings.meilleurs_signaux_historiques_bruts.map(
        (entry) => entry.family,
      ),
    ),
  );
  return (
    <figure className="hu-competition-matrix">
      <figcaption>
        <strong>Familles × championnats</strong>
        <span>
          Présence d’au moins un signal historique brut dans les classements
          contractuels.
        </span>
      </figcaption>
      <div className="hu-matrix-grid">
        <div className="hu-matrix-corner">Famille</div>
        {hypothesisCompetitions.map((competition) => (
          <strong key={competition.canonical_competition_key}>
            {competition.display_name_fr}
          </strong>
        ))}
        {(representedFamilies.length ? representedFamilies : ["AUCUNE"]).map(
          (family) => (
            <div className="hu-matrix-row" key={family}>
              <span>
                {hypothesisFamilies.find((item) => item.family === family)
                  ?.display_name_fr ?? family}
              </span>
              {hypothesisCompetitions.map((competition) => {
                const rankings = competitionRankings(
                  competition.display_name_fr,
                ).meilleurs_signaux_historiques_bruts;
                const active = rankings.some((entry) => entry.family === family);
                return (
                  <i
                    aria-label={`${competition.display_name_fr} : ${active ? "signal présent" : "aucun signal classé"}`}
                    className={active ? "active" : ""}
                    data-label={competition.display_name_fr}
                    key={competition.canonical_competition_key}
                  >
                    {active ? "Présent" : "Aucun"}
                  </i>
                );
              })}
            </div>
          ),
        )}
      </div>
      <p className="hu-chart-summary">
        L’absence de case active signifie uniquement qu’aucun signal n’est
        classé dans le contrat actuel, pas que la famille est impossible.
      </p>
    </figure>
  );
}

function LongTailCollection({ detailed }: { detailed: boolean }) {
  const entries = hypothesisRankings.longue_traine_a_surveiller;
  return (
    <div className="hu-long-tail-grid">
      {entries.map((node) => (
        <article key={node.node_id}>
          <div>
            <ScientificStatusBadge status={node.materialization_disposition} />
            <span>{node.parent_ids.length} parent{node.parent_ids.length > 1 ? "s" : ""}</span>
          </div>
          <h3>{node.display_rule_fr}</h3>
          <div className="hu-tag-list">
            <TagChip kind="family" tagId={`family:${node.family}`}>
              {familyDisplayName(node.family)}
            </TagChip>
            <TagChip tagId={`subfamily:${node.subfamily}`}>
              {subfamilyDisplayName(node.subfamily)}
            </TagChip>
          </div>
          <p>
            Cette combinaison est plausible mais encore trop rare pour être
            évaluée correctement. Robin la conserve pour les futures
            rencontres.
          </p>
          {detailed ? (
            <dl>
              <div>
                <dt>Support</dt>
                <dd>{node.support == null ? "Encore insuffisant" : formatNumber(node.support)}</dd>
              </div>
              <div>
                <dt>Données</dt>
                <dd>
                  {node.data_gates.map(scientificStatusLabel).join(" · ")}
                </dd>
              </div>
            </dl>
          ) : null}
          <Link className="hu-text-link" href={`/hypotheses/${node.node_id}`}>
            Voir la branche →
          </Link>
        </article>
      ))}
    </div>
  );
}

export function HypothesisRankingsPage({
  initialCompetition = "GLOBAL",
  variant = "classements",
}: {
  initialCompetition?: string;
  variant?: RankingsPageVariant;
}) {
  const { mode } = useViewMode();
  const [competition, setCompetition] = useState(initialCompetition);
  const [family, setFamily] = useState("ALL");
  const [market, setMarket] = useState("ALL");
  const [origin, setOrigin] = useState("ALL");
  const [cutoff, setCutoff] = useState("ALL");
  const detailed = mode !== "discovery";
  const evidenceAxes = useMemo(
    () => ({ cutoff, market, origin }),
    [cutoff, market, origin],
  );
  const allRankingEntries = useMemo(() => {
    const byId = new Map<string, RankingEntry>();
    for (const entry of [
      ...hypothesisRankings.meilleurs_signaux_historiques_bruts,
      ...hypothesisRankings.meilleures_priorites_exploratoires,
      ...hypothesisRankings.meilleures_observations_prospectives,
      ...hypothesisRankings.strategies_validees,
    ]) {
      byId.set(entry.hypothesis_id, entry);
    }
    return [...byId.values()];
  }, []);
  const marketOptions = useMemo(
    () => axisOptions(allRankingEntries, "market", "marketLabel"),
    [allRankingEntries],
  );
  const originOptions = useMemo(
    () => axisOptions(allRankingEntries, "origin", "originLabel"),
    [allRankingEntries],
  );
  const cutoffOptions = useMemo(
    () => axisOptions(allRankingEntries, "cutoff", "cutoffLabel"),
    [allRankingEntries],
  );
  const joinedEvidenceCount = useMemo(
    () =>
      allRankingEntries.filter((entry) => {
        const evidence = evidenceFor(entry);
        return evidence.market || evidence.origin || evidence.cutoff;
      }).length,
    [allRankingEntries],
  );

  useEffect(() => {
    const search = new URL(window.location.href).searchParams;
    queueMicrotask(() => {
      setFamily(search.get("famille") ?? "ALL");
      setMarket(search.get("marche") ?? "ALL");
      setOrigin(search.get("origine") ?? "ALL");
      setCutoff(search.get("heure-limite") ?? "ALL");
    });
  }, []);

  const scopedRankings = useMemo(() => {
    const base =
      competition === "GLOBAL"
        ? hypothesisRankings.meilleurs_signaux_historiques_bruts
        : competitionRankings(competition).meilleurs_signaux_historiques_bruts;
    return base.filter(
      (entry) =>
        (family === "ALL" || entry.family === family) &&
        matchesEvidenceAxes(entry, evidenceAxes),
    );
  }, [competition, evidenceAxes, family]);

  const priorities = useMemo(() => {
    const base =
      competition === "GLOBAL"
        ? hypothesisRankings.meilleures_priorites_exploratoires
        : [];
    return base.filter(
      (entry) =>
        (family === "ALL" || entry.family === family) &&
        matchesEvidenceAxes(entry, evidenceAxes),
    );
  }, [competition, evidenceAxes, family]);

  const validatedStrategies = useMemo(() => {
    const base =
      competition === "GLOBAL"
        ? hypothesisRankings.strategies_validees
        : competitionRankings(competition).strategies_validees;
    return base.filter(
      (entry) =>
        (family === "ALL" || entry.family === family) &&
        matchesEvidenceAxes(entry, evidenceAxes),
    );
  }, [competition, evidenceAxes, family]);

  const prospectiveRankings = useMemo(
    () =>
      hypothesisRankings.meilleures_observations_prospectives.filter(
        (entry) =>
          (competition === "GLOBAL" ||
            entry.competition === competition) &&
          (family === "ALL" || entry.family === family) &&
          matchesEvidenceAxes(entry, evidenceAxes),
      ),
    [competition, evidenceAxes, family],
  );

  const updateUrlFilter = (parameter: string, value: string) => {
    const url = new URL(window.location.href);
    if (value === "ALL" || value === "GLOBAL") {
      url.searchParams.delete(parameter);
    } else {
      url.searchParams.set(parameter, value);
    }
    window.history.replaceState({}, "", url);
  };

  const updateCompetition = (value: string) => {
    setCompetition(value);
    updateUrlFilter("competition", value);
  };

  if (variant === "longue-traine") {
    return (
      <div className="hu-page hu-rankings-page">
        <HypothesisBreadcrumbs
          items={[
            { href: "/robin-live", label: "Accueil" },
            { href: "/hypotheses", label: "Hypothèses" },
            { label: "Longue traîne" },
          ]}
        />
        <HypothesisSubnav />
        <header className="hu-page-header">
          <div>
            <p className="hu-kicker">Branches rares conservées</p>
            <h1>La longue traîne</h1>
            <p>
              Des combinaisons plausibles, mais trop rares pour produire une
              conclusion fiable aujourd’hui.
            </p>
          </div>
          <UniverseMetric
            detail="dans le contrat borné"
            label="Branches surveillées"
            tone="violet"
            value={hypothesisRankings.longue_traine_a_surveiller.length}
          />
        </header>
        <LongTailCollection detailed={detailed} />
      </div>
    );
  }

  if (variant === "observations") {
    return (
      <div className="hu-page hu-rankings-page">
        <HypothesisBreadcrumbs
          items={[
            { href: "/robin-live", label: "Accueil" },
            { href: "/hypotheses", label: "Hypothèses" },
            { label: "Observations prospectives" },
          ]}
        />
        <HypothesisSubnav />
        <header className="hu-page-header">
          <div>
            <p className="hu-kicker">Après gel des règles</p>
            <h1>Observations prospectives</h1>
            <p>
              Le passé reste séparé de ce qui arrive après le gel. Aucun
              résultat n’est complété avant son règlement réel.
            </p>
          </div>
        </header>
        <div className="hu-prospective-grid">
          {hypothesisIntelligence.prospectiveObservations.map((observation) => (
            <article className="hu-section hu-surface" key={observation.hypothesisId}>
              <div className="hu-ranking-card-head">
                <strong>{observation.hypothesisId}</strong>
                <ScientificStatusBadge status={observation.status} />
              </div>
              {detailed ? (
                <dl className="hu-detail-list" data-view-mode="analysis">
                  <div><dt>Matchs examinés</dt><dd>{formatNumber(observation.fixturesExamined)}</dd></div>
                  <div><dt>Matchs éligibles</dt><dd>{formatNumber(observation.eligibleMatches)}</dd></div>
                  <div><dt>Observations réglées</dt><dd>{formatNumber(observation.settledObservations)}</dd></div>
                  <div><dt>Résultat prospectif</dt><dd>{observation.prospectiveProfitUnits == null ? "Aucune observation" : formatNumber(observation.prospectiveProfitUnits, 2)}</dd></div>
                </dl>
              ) : (
                <p data-view-mode="discovery">
                  Ce contrat attend encore des rencontres observées après son
                  gel. Aucun résultat passé ne remplit cet espace.
                </p>
              )}
              <Link className="hu-text-link" href={`/hypotheses/${observation.hypothesisId}`}>
                Ouvrir le contrat →
              </Link>
            </article>
          ))}
        </div>
        {hypothesisIntelligence.prospectiveObservations.some(
          (observation) =>
            observation.settledObservations > 0 ||
            observation.prospectiveProfitUnits != null,
        ) ? null : (
          <HonestEmptyState title="Aucun résultat prospectif réglé">
            {formatNumber(
              hypothesisIntelligence.prospectiveObservations.length,
            )}
            {hypothesisIntelligence.prospectiveObservations.length > 1
              ? " contrats sont actifs, mais aucune observation réelle n’est encore réglée."
              : " contrat est actif, mais aucune observation réelle n’est encore réglée."}{" "}
            La chronologie restera vide jusqu’à l’arrivée d’une preuve
            admissible.
          </HonestEmptyState>
        )}
      </div>
    );
  }

  return (
    <div className="hu-page hu-rankings-page">
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { label: "Classements" },
        ]}
      />
      <HypothesisSubnav />
      <header className="hu-page-header">
        <div>
          <p className="hu-kicker">Catégories scientifiques séparées</p>
          <h1>Classements des hypothèses</h1>
          <p>
            Un bon résultat historique, une priorité exploratoire, une
            observation prospective et une stratégie validée ne sont jamais
            mélangés.
          </p>
        </div>
        <UniverseMetric
          detail="uniquement statut VALIDATED"
          label="Stratégies validées"
          tone="coral"
          value={hypothesisFunnel.validated_strategies}
        />
      </header>

      <section
        aria-label={`Lecture ${mode === "discovery" ? "Découverte" : mode === "analysis" ? "Analyse" : "Expert"}`}
        className="hu-section hu-surface hu-mode-summary"
        data-view-mode={mode}
      >
        <p className="hu-kicker">
          Vue {mode === "discovery" ? "Découverte" : mode === "analysis" ? "Analyse" : "Expert"}
        </p>
        <h2>
          {mode === "discovery"
            ? "Comprendre les pistes avant les chiffres"
            : mode === "analysis"
              ? "Comparer les preuves et leurs limites"
              : "Relier les classements à leurs contrats"}
        </h2>
        <p>
          {mode === "discovery"
            ? "Cette vue montre ce que Robin explore et sépare clairement une piste d’une stratégie validée."
            : mode === "analysis"
              ? "Cette vue ajoute support, stabilité, risque et séparation entre simulation historique et observation prospective."
              : "Cette vue conserve l’analyse et ajoute les identifiants techniques nécessaires à l’audit."}
        </p>
      </section>

      <section className="hu-ranking-filters" aria-label="Portée du classement">
        <div className="hu-league-tabs" role="group" aria-label="Championnat">
          <button
            aria-pressed={competition === "GLOBAL"}
            onClick={() => updateCompetition("GLOBAL")}
            type="button"
          >
            Global
          </button>
          {hypothesisCompetitions.map((item) => (
            <button
              aria-pressed={competition === item.display_name_fr}
              key={item.canonical_competition_key}
              onClick={() => updateCompetition(item.display_name_fr)}
              type="button"
            >
              {item.display_name_fr}
            </button>
          ))}
        </div>
        <div className="hu-ranking-filter-fields">
          <label>
            Famille
            <select
              aria-label="Famille"
              onChange={(event) => {
                setFamily(event.target.value);
                updateUrlFilter("famille", event.target.value);
              }}
              value={family}
            >
              <option value="ALL">Toutes les familles</option>
              {hypothesisFamilies.map((item) => (
                <option key={item.family} value={item.family}>
                  {item.display_name_fr}
                </option>
              ))}
            </select>
          </label>
          <label>
            Marché
            <select
              aria-label="Marché"
              onChange={(event) => {
                setMarket(event.target.value);
                updateUrlFilter("marche", event.target.value);
              }}
              value={market}
            >
              <option value="ALL">Tous les marchés documentés</option>
              {marketOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Origine
            <select
              aria-label="Origine"
              onChange={(event) => {
                setOrigin(event.target.value);
                updateUrlFilter("origine", event.target.value);
              }}
              value={origin}
            >
              <option value="ALL">Toutes les origines documentées</option>
              {originOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Heure limite
            <select
              aria-label="Heure limite"
              onChange={(event) => {
                setCutoff(event.target.value);
                updateUrlFilter("heure-limite", event.target.value);
              }}
              value={cutoff}
            >
              <option value="ALL">Toutes les heures documentées</option>
              {cutoffOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p aria-live="polite" className="hu-ranking-join-state">
          {joinedEvidenceCount
            ? `${formatNumber(joinedEvidenceCount)} hypothèse${joinedEvidenceCount > 1 ? "s reliées" : " reliée"} aux preuves de marché, d’origine ou d’heure limite.`
            : "Aucune jointure contractuelle ne permet encore de filtrer par marché, origine ou heure limite."}
        </p>
      </section>

      <section className="hu-section">
        <UniverseSectionHeading
          eyebrow={competition === "GLOBAL" ? "Vue globale" : competition}
          subtitle="Intéressants dans la simulation historique, mais non validés."
          title="Meilleurs signaux historiques bruts"
        />
        {scopedRankings.length ? (
          <div className="hu-ranking-grid">
            {scopedRankings.map((entry) => (
              detailed ? (
                <RankingCard entry={entry} key={entry.hypothesis_id} />
              ) : (
                <DiscoveryRankingCard entry={entry} key={entry.hypothesis_id} />
              )
            ))}
          </div>
        ) : (
          <HonestEmptyState title="Aucun signal historique classé">
            Le contrat ne publie aucun signal pour cette portée. Robin n’en
            déduit pas que la compétition ou la famille est sans intérêt.
          </HonestEmptyState>
        )}
      </section>

      {detailed ? (
        <>
          <section className="hu-section hu-surface" data-view-mode="analysis">
            <UniverseSectionHeading
              subtitle="Ordre de recherche, pas ordre de mise."
              title="Priorités exploratoires"
            />
            {priorities.length ? (
              <ol className="hu-priority-list">
                {priorities.map((entry) => (
                  <li key={entry.hypothesis_id}>
                    <span>{entry.rank}</span>
                    <div>
                      <strong>{entry.hypothesis_id}</strong>
                      <p>{entry.label_fr} · {entry.competition}</p>
                    </div>
                    <ScientificStatusBadge status={entry.status} />
                    <Link href={`/hypotheses/${entry.hypothesis_id}`}>Analyser</Link>
                  </li>
                ))}
              </ol>
            ) : (
              <HonestEmptyState title="Aucune priorité publiée">
                Les métriques nécessaires au classement ne sont pas toutes
                disponibles pour cette portée.
              </HonestEmptyState>
            )}
          </section>

          <section className="hu-section" data-view-mode="analysis">
            <UniverseSectionHeading
              subtitle="Les graphiques montrent les limites autant que les résultats."
              title="Lire la solidité, pas seulement le rang"
            />
            <div className="hu-chart-grid">
              <RankingScatter entries={scopedRankings} />
              <FalsePositiveChart entries={scopedRankings} />
            </div>
            <CompetitionMatrix />
          </section>

          <section className="hu-section" id="observations-prospectives">
            <UniverseSectionHeading
              action={<Link className="hu-text-link" href="/hypotheses/observations">Voir les contrats →</Link>}
              title="Observations prospectives"
            />
            {prospectiveRankings.length ? (
              <div className="hu-ranking-grid">
                {prospectiveRankings.map((entry) => (
                  <RankingCard entry={entry} key={entry.hypothesis_id} />
                ))}
              </div>
            ) : (
              <HonestEmptyState title="Aucune observation prospective classée">
                Les contrats sont gelés, mais aucun résultat réel n’est encore
                réglé. L’historique ne remplit jamais cet espace.
              </HonestEmptyState>
            )}
          </section>
        </>
      ) : null}

      <section className="hu-section" id="strategies-validees">
        <UniverseSectionHeading title="Stratégies validées" />
        {validatedStrategies.length ? (
          <div className="hu-ranking-grid">
            {validatedStrategies.map((entry) =>
              detailed ? (
                <RankingCard entry={entry} key={entry.hypothesis_id} />
              ) : (
                <DiscoveryRankingCard entry={entry} key={entry.hypothesis_id} />
              ),
            )}
          </div>
        ) : (
          <HonestEmptyState icon="∅" title="Aucune stratégie n’est encore scientifiquement validée">
            Robin distingue les résultats intéressants des preuves suffisamment
            solides pour être considérées comme fiables.
          </HonestEmptyState>
        )}
      </section>

      <section className="hu-section">
        <UniverseSectionHeading
          action={<Link className="hu-text-link" href="/hypotheses/longue-traine">Tout voir →</Link>}
          title="Longue traîne"
        />
        <LongTailCollection detailed={detailed} />
      </section>

      {mode === "expert" ? (
        <section className="hu-section hu-expert-proof" data-view-mode="expert">
          <UniverseSectionHeading
            eyebrow="Vue Expert"
            title="Portée contractuelle brute"
          />
          <dl className="hu-technical-grid">
            <div>
              <dt>Contrat source</dt>
              <dd><code>hypothesis-global-rankings</code></dd>
            </div>
            <div>
              <dt>Statut validé exigé</dt>
              <dd><code>VALIDATED</code></dd>
            </div>
            <div>
              <dt>Championnat</dt>
              <dd><code>{competition}</code></dd>
            </div>
            <div>
              <dt>Famille</dt>
              <dd><code>{family}</code></dd>
            </div>
          </dl>
        </section>
      ) : null}
    </div>
  );
}
