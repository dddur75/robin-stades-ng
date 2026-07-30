"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import { formatDateTime, formatNumber } from "../../i18n";
import {
  familyIcon,
  familySlug,
  generatedHypothesisRules,
  hypothesisActivity,
  hypothesisFamilies,
  hypothesisFunnel,
  hypothesisProspectiveFreeze,
  hypothesisRankings,
  hypothesisSecurity,
  hypothesisSummary,
} from "../../lib/hypothesis-universe";
import { matches, nextCaptures } from "../../lib/presentation";
import { useViewMode } from "../common/view-mode";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  ScientificStatusBadge,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

type VisitSnapshot = {
  branches: number;
  families: number;
  observations: number;
  properties: number;
  recordedAt: string;
  tested: number;
};

type VisitComparison =
  | { kind: "first" }
  | {
      kind: "comparison";
      branches: number;
      families: number;
      observations: number;
      properties: number;
      recordedAt: string;
      tested: number;
    };

const visitStorageKey = "robin-hypothesis-universe-last-visit-v1";

function currentVisitSnapshot(): VisitSnapshot {
  return {
    branches: hypothesisSummary.materialized_candidates,
    families: hypothesisSummary.property_families,
    observations: hypothesisActivity.hypothesis_observations,
    properties: hypothesisSummary.properties,
    recordedAt: new Date().toISOString(),
    tested: hypothesisSummary.executed_candidates,
  };
}

function SinceLastVisit() {
  const [comparison, setComparison] = useState<VisitComparison | null>(null);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const current = currentVisitSnapshot();
      const saved = window.localStorage.getItem(visitStorageKey);
      if (!saved) {
        setComparison({ kind: "first" });
      } else {
        try {
          const previous = JSON.parse(saved) as VisitSnapshot;
          setComparison({
            branches: current.branches - previous.branches,
            families: current.families - previous.families,
            kind: "comparison",
            observations: current.observations - previous.observations,
            properties: current.properties - previous.properties,
            recordedAt: previous.recordedAt,
            tested: current.tested - previous.tested,
          });
        } catch {
          setComparison({ kind: "first" });
        }
      }
      window.localStorage.setItem(visitStorageKey, JSON.stringify(current));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (comparison == null) {
    return <p className="hu-muted">Comparaison locale en cours…</p>;
  }
  if (comparison.kind === "first") {
    return (
      <HonestEmptyState icon="✦" title="Première visite sur cet appareil">
        Robin mémorise uniquement les compteurs publics dans ce navigateur. Au
        prochain passage, les écarts seront calculés sans créer de compte.
      </HonestEmptyState>
    );
  }

  const changes = [
    ["familles", comparison.families],
    ["propriétés", comparison.properties],
    ["branches matérialisées", comparison.branches],
    ["règles testées", comparison.tested],
    ["observations prospectives", comparison.observations],
  ] as const;
  const positiveChanges = changes.filter(([, value]) => value > 0);

  return (
    <div>
      <p className="hu-muted">
        Dernier passage local le {formatDateTime(comparison.recordedAt, true)}.
      </p>
      {positiveChanges.length ? (
        <ul className="hu-change-list">
          {positiveChanges.map(([label, value]) => (
            <li key={label}>
              <strong>+{formatNumber(value)}</strong>
              <span>{label}</span>
            </li>
          ))}
        </ul>
      ) : (
        <HonestEmptyState title="Aucun compteur contractuel n’a changé">
          Robin ne signale une nouveauté que lorsqu’un contrat borné présente
          une valeur différente de celle enregistrée lors de votre visite.
        </HonestEmptyState>
      )}
    </div>
  );
}

export function ScientificFunnel() {
  const frozenContracts = hypothesisProspectiveFreeze.contracts.length;
  const realObservations = hypothesisActivity.hypothesis_observations;
  const settledObservations = hypothesisActivity.prospective_settlements;
  const stages = [
    {
      label: "Règles générées",
      value: generatedHypothesisRules,
    },
    {
      label: "Règles matérialisées",
      value: hypothesisSummary.materialized_candidates,
    },
    {
      label: "Règles testées",
      value: hypothesisSummary.executed_candidates,
    },
    {
      label: "Contrats gelés",
      value: frozenContracts,
    },
    {
      label: "Observations réelles",
      value: realObservations,
    },
    {
      label: "Observations réglées",
      value: settledObservations,
    },
    {
      label: "Stratégies validées",
      value: hypothesisFunnel.validated_strategies,
    },
  ];
  const maximum = Math.max(...stages.map((stage) => stage.value), 1);
  const logarithmicWidth = (value: number) =>
    value === 0
      ? 0
      : (Math.log10(value + 1) / Math.log10(maximum + 1)) * 100;

  return (
    <figure className="hu-funnel">
      <figcaption>
        <strong>Entonnoir scientifique</strong>
        <span>
          Chaque étage exige davantage de preuves. L’état prospectif sépare le
          gel des contrats, les observations réelles et leur règlement.
        </span>
      </figcaption>
      <ol>
        {stages.map((stage, index) => (
          <li key={stage.label}>
            <div>
              <span>{stage.label}</span>
              <strong>{formatNumber(stage.value)}</strong>
            </div>
            <span
              aria-hidden="true"
              data-zero={stage.value === 0 ? "true" : undefined}
              style={{
                width: `${logarithmicWidth(stage.value)}%`,
              }}
            />
            {index < stages.length - 1 ? (
              <small aria-hidden="true">↓</small>
            ) : null}
          </li>
        ))}
      </ol>
      <p className="hu-chart-summary">
        Les largeurs utilisent une échelle logarithmique pour rendre les petits
        volumes lisibles ; une valeur nulle ne produit aucune barre.{" "}
        Résumé : {formatNumber(generatedHypothesisRules)} règles générées,
        {" "}
        {formatNumber(hypothesisSummary.executed_candidates)} déjà testées,
        {" "}
        {formatNumber(frozenContracts)} contrats gelés,{" "}
        {formatNumber(realObservations)} observations réelles,{" "}
        {formatNumber(settledObservations)} observations réglées et{" "}
        {formatNumber(hypothesisFunnel.validated_strategies)} stratégies validées.
      </p>
    </figure>
  );
}

function FamilyUniverseMap() {
  return (
    <div className="hu-universe-map" role="list">
      {hypothesisFamilies.map((family, index) => (
        <Link
          className={`hu-orbit-family hu-orbit-${(index % 6) + 1}`}
          href={`/hypotheses/familles/${familySlug(family.family)}`}
          key={family.family}
          role="listitem"
        >
          <span aria-hidden="true">{familyIcon(family.family)}</span>
          <strong>{family.display_name_fr}</strong>
          <small>{formatNumber(family.property_count)} propriétés</small>
          <ScientificStatusBadge status={family.availability_status} />
        </Link>
      ))}
    </div>
  );
}

export function HypothesisUniversePage() {
  const { mode } = useViewMode();
  const untested =
    generatedHypothesisRules - hypothesisSummary.executed_candidates;
  const exploratoryTested =
    hypothesisSummary.executed_candidates - hypothesisFunnel.validated_strategies;
  const keyMetrics = useMemo(
    () => [
      {
        detail: "combinées par le moteur",
        label: "Règles générées",
        tone: "teal" as const,
        value: generatedHypothesisRules,
      },
      {
        detail: "dans le pilote borné",
        label: "Règles déjà testées",
        tone: "blue" as const,
        value: hypothesisSummary.executed_candidates,
      },
      {
        detail: "testées mais non validées",
        label: "Signaux exploratoires",
        tone: "gold" as const,
        value: exploratoryTested,
      },
      {
        detail: "après gel des règles",
        label: "En observation prospective",
        tone: "violet" as const,
        value: hypothesisSummary.prospectively_frozen_candidates,
      },
      {
        detail: "à ce jour",
        label: "Stratégies validées",
        tone: "coral" as const,
        value: hypothesisFunnel.validated_strategies,
      },
    ],
    [exploratoryTested],
  );

  return (
    <div className="hu-page hu-universe-page">
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { label: "Hypothèses" },
        ]}
      />
      <HypothesisSubnav />

      <section className="hu-hero">
        <div className="hu-hero-copy">
          <p className="hu-kicker">Recherche football · univers vérifiable</p>
          <h1>L’Univers des hypothèses</h1>
          <p className="hu-hero-lead">
            Robin transforme les données du football en arbres d’idées, puis
            teste chaque branche sans réécrire le passé.
          </p>
          <p className="hu-hero-explainer">
            Robin explore <strong>{formatNumber(hypothesisSummary.property_families)} grandes familles</strong>{" "}
            et <strong>{formatNumber(hypothesisSummary.properties)} propriétés football</strong>.
            Le moteur les combine en arbres, puis teste uniquement les branches
            compatibles avec les données disponibles.
          </p>
          <div className="hu-hero-actions">
            <Link className="hu-primary-action" href="/hypotheses/arbres">
              Explorer les arbres
              <span aria-hidden="true">↗</span>
            </Link>
            <Link className="hu-secondary-action" href="/hypotheses/familles">
              Voir les {formatNumber(hypothesisSummary.property_families)} familles
            </Link>
          </div>
          <p className="hu-safety-line">
            <span aria-hidden="true">◉</span>
            Aucun pari réel · aucune promotion automatique · données manquantes
            visibles
          </p>
        </div>
        <div className="hu-hero-visual" aria-hidden="true">
          <span className="hu-orbit hu-orbit-a" />
          <span className="hu-orbit hu-orbit-b" />
          <span className="hu-orbit hu-orbit-c" />
          <span className="hu-hero-core">
            <strong>{formatNumber(hypothesisSummary.property_families)}</strong>
            familles
          </span>
          <i style={{ "--orbit-index": 1 } as CSSProperties}>Tactique</i>
          <i style={{ "--orbit-index": 2 } as CSSProperties}>Météo</i>
          <i style={{ "--orbit-index": 3 } as CSSProperties}>Marché</i>
          <i style={{ "--orbit-index": 4 } as CSSProperties}>Joueurs</i>
          <i style={{ "--orbit-index": 5 } as CSSProperties}>Fatigue</i>
        </div>
      </section>

      <section aria-label="Chiffres clés" className="hu-key-metrics">
        {keyMetrics.map((metric) => (
          <UniverseMetric {...metric} key={metric.label} />
        ))}
      </section>

      <aside
        className="hu-zero-proof"
        data-has-validated={
          hypothesisFunnel.validated_strategies > 0 ? "true" : "false"
        }
      >
        <span aria-hidden="true">
          {formatNumber(hypothesisFunnel.validated_strategies)}
        </span>
        <div>
          {hypothesisFunnel.validated_strategies === 0 ? (
            <>
              <strong>Zéro stratégie validée est un résultat honnête.</strong>
              <p>
                Un résultat historique intéressant ne suffit pas. Robin attend
                une preuve prospective stable, un support suffisant et un risque
                de faux positif maîtrisé avant d’employer le mot « validée ».
              </p>
            </>
          ) : (
            <>
              <strong>
                {formatNumber(hypothesisFunnel.validated_strategies)} stratégie
                {hypothesisFunnel.validated_strategies > 1 ? "s" : ""} ont
                franchi tous les seuils.
              </strong>
              <p>
                Elles restent séparées des priorités exploratoires et des
                résultats historiques bruts. Le classement publie leurs preuves
                contractuelles.
              </p>
            </>
          )}
        </div>
        <Link href="/hypotheses/classements#strategies-validees">
          {hypothesisFunnel.validated_strategies === 0
            ? "Comprendre ce seuil"
            : "Voir les stratégies validées"}
        </Link>
      </aside>

      <section className="hu-section">
        <UniverseSectionHeading
          action={
            <Link className="hu-text-link" href="/hypotheses/familles">
              Catalogue complet →
            </Link>
          }
          eyebrow="Carte vivante"
          subtitle="Chaque point ouvre une famille issue du catalogue contractuel. Aucune famille n’est ajoutée manuellement."
          title="Une constellation de questions football"
        />
        <FamilyUniverseMap />
      </section>

      <section className="hu-two-column">
        <div className="hu-section hu-surface">
          <UniverseSectionHeading
            eyebrow="Progression locale"
            title="Depuis votre dernière visite"
          />
          <SinceLastVisit />
        </div>
        <div className="hu-section hu-surface">
          <UniverseSectionHeading
            eyebrow="Maintenant"
            title="Activité actuelle"
          />
          <dl className="hu-activity-list">
            <div>
              <dt>Rencontres suivies</dt>
              <dd>{formatNumber(matches.length)}</dd>
            </div>
            <div>
              <dt>Prochaine capture planifiée</dt>
              <dd>
                {nextCaptures[0]
                  ? `${nextCaptures[0].match} · ${nextCaptures[0].family}`
                  : "Aucune capture due"}
              </dd>
            </div>
            <div>
              <dt>Observations prospectives</dt>
              <dd>{formatNumber(hypothesisActivity.hypothesis_observations)}</dd>
            </div>
            <div>
              <dt>Données encore attendues</dt>
              <dd>{formatNumber(hypothesisSummary.data_gate_blocked_candidates)} branches</dd>
            </div>
            <div>
              <dt>Paris réels</dt>
              <dd>{formatNumber(hypothesisActivity.real_bets)}</dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="hu-section">
        <UniverseSectionHeading
          eyebrow="De l’idée à la preuve"
          subtitle="La largeur diminue avec le niveau d’exigence scientifique."
          title="Pourquoi toutes les branches ne vont pas au bout"
        />
        <div className="hu-funnel-layout">
          <ScientificFunnel />
          <aside className="hu-data-state">
            <h3>État des branches</h3>
            <dl>
              {Object.entries(hypothesisFunnel.counts).map(([status, value]) => (
                <div key={status}>
                  <dt>
                    <ScientificStatusBadge status={status} />
                  </dt>
                  <dd>{formatNumber(value)}</dd>
                </div>
              ))}
            </dl>
            <p>
              {formatNumber(untested)} branches ne sont pas encore testées :
              certaines attendent des données, d’autres un prochain cycle de
              calcul.
            </p>
          </aside>
        </div>
      </section>

      <section className="hu-section">
        <UniverseSectionHeading
          eyebrow={`Vue ${mode === "discovery" ? "Découverte" : mode === "analysis" ? "Analyse" : "Expert"}`}
          subtitle="Le même état scientifique, avec un niveau de détail adapté."
          title="Trois lectures, aucune vérité différente"
        />
        <div className="hu-reading-modes">
          <article className={mode === "discovery" ? "active" : ""}>
            <span>01</span>
            <h3>Découverte</h3>
            <p>Familles, arbres, chiffres clés et explications sans jargon.</p>
          </article>
          <article className={mode === "analysis" ? "active" : ""}>
            <span>02</span>
            <h3>Analyse</h3>
            <p>Support, stabilité, risque et historique séparé du prospectif.</p>
          </article>
          <article className={mode === "expert" ? "active" : ""}>
            <span>03</span>
            <h3>Expert</h3>
            <p>Règles techniques, hashes, provenance, contrats et relations.</p>
          </article>
        </div>
      </section>

      <section className="hu-proof-footer">
        <div>
          <p className="hu-kicker">Périmètre scientifique</p>
          <h2>Voir ce qui résiste, pas seulement ce qui brille.</h2>
          <p>
            {hypothesisRankings.warning_fr} Les pertes, blocages et limites
            restent visibles dans chaque parcours.
          </p>
        </div>
        <div className="hu-locks">
          <ScientificStatusBadge
            status={hypothesisSecurity.PRODUCTION_LOCKED ? "PRODUCTION_LOCKED" : "NOT_LOCKED"}
          />
          <span>Paris réels : {hypothesisSecurity.REAL_BETS ? "activés" : "désactivés"}</span>
          <span>Appels fournisseur : {formatNumber(hypothesisSecurity.provider_calls)}</span>
        </div>
      </section>
    </div>
  );
}
