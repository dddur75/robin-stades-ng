"use client";

import Link from "next/link";

import { AnalysisOnly, ExpertOnly } from "../common/view-mode";
import { formatDateTime, formatNumber } from "../../i18n";
import {
  familyBlockingReason,
  familyDescription,
  familyIcon,
  familyRootNodes,
  familySlug,
  familyStats,
  hypothesisActivity,
  hypothesisChildrenByParent,
  hypothesisRankings,
  hypothesisRankingsByFamily,
  hypothesisTags,
  type HypothesisFamily,
} from "../../lib/hypothesis-universe";
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

const publicEntityLabels: Record<string, string> = {
  MATCH: "Rencontres et contexte",
  STADIUM: "Stades",
  PITCH: "Terrains",
  WEATHER_OBSERVATION: "Observations météorologiques datées",
  TRAVEL: "Déplacements",
  SCHEDULE: "Calendrier",
  TEAM_STRENGTH: "Force des équipes",
  TEAM_ATTACK: "Attaque des équipes",
  TEAM_DEFENCE: "Défense des équipes",
  POSSESSION_STATE: "Possession et pressing",
  SET_PIECE_STATE: "Coups de pied arrêtés",
  PLAYER: "Joueurs",
  PLAYER_PROFILE: "Profils de joueurs",
  LINEUP: "Compositions",
  PLAYER_AVAILABILITY: "Disponibilités des joueurs",
  DISCIPLINE_STATE: "Discipline et arbitrage",
  TACTICAL_STATE: "Structures tactiques",
  COACH: "Encadrement",
  GOALKEEPER: "Gardiens",
  BENCH: "Banc",
  TEAM_NETWORK: "Complémentarités",
  NEWS_ITEM: "Informations datées",
  MARKET_SNAPSHOT: "Prix du marché datés",
  TRAINING_LOAD: "Charge d’entraînement",
  MEDICAL_STATE: "Santé et retour au jeu",
  MATCH_EVENT: "Événements du match",
  SQUAD: "Effectif",
  DATA_SOURCE: "Sources et provenance",
};

const publicSubfamilyLabels: Record<string, string> = {
  CLIMATE: "Climat du déplacement",
  COMMON: "Formation habituelle",
  CROSSWIND: "Vent traversier",
  FORECAST: "Prévision",
  FORMATION: "Confrontations de systèmes",
  FORMATIONS: "Structures avec et sans ballon",
  HUMIDITY: "Humidité",
  OBSERVED: "Observation réelle",
  PITCH: "État du terrain",
  RAIN: "Pluie",
  SNOW: "Neige",
  TEMPERATURE: "Température",
  THERMAL: "Chaleur ressentie",
  USUAL: "Usage habituel",
  VISIBILITY: "Visibilité",
  WIND: "Vent et rafales",
};

const familyAxes: Partial<Record<string, string[]>> = {
  FORMATION_STRUCTURE: [
    "FORMATION",
    "FORMATIONS",
    "COMMON",
    "USUAL",
  ],
  WEATHER: [
    "TEMPERATURE",
    "THERMAL",
    "HUMIDITY",
    "RAIN",
    "SNOW",
    "WIND",
    "CROSSWIND",
    "VISIBILITY",
    "PITCH",
    "CLIMATE",
    "FORECAST",
    "OBSERVED",
  ],
};

function presentSubfamily(value: string) {
  return (
    publicSubfamilyLabels[value] ??
    value
      .replaceAll("_", " ")
      .toLocaleLowerCase("fr-FR")
      .replace(/^./, (letter) => letter.toLocaleUpperCase("fr-FR"))
  );
}

function NativeFamilyFocus({ family }: { family: HypothesisFamily }) {
  if (family.family === "WEATHER") {
    return (
      <section className="hu-section hu-native-focus">
        <UniverseSectionHeading
          eyebrow="Famille native"
          subtitle="Aucune valeur météorologique n’est inventée dans cette vue."
          title="Une météo connue au bon moment"
        />
        <blockquote>
          Robin ne peut utiliser dans une prédiction que la météo connue au
          moment où la prédiction est gelée.
        </blockquote>
        <div className="hu-native-proof-grid">
          <article>
            <h3>Source</h3>
            <p>
              Archive libre, licenciée et datée : non disponible dans le
              contrat actuel.
            </p>
          </article>
          <article>
            <h3>Précision</h3>
            <p>
              Non mesurable tant que la source temporelle n’est pas
              admissible.
            </p>
          </article>
          <article>
            <h3>Interactions à explorer</h3>
            <div className="hu-tag-list">
              {["Tactique", "Gardien", "Centres", "Fatigue", "Terrain"].map(
                (label) => (
                  <TagChip key={label}>{label}</TagChip>
                ),
              )}
            </div>
            <p>Ces liens sont des directions de recherche, pas des résultats.</p>
          </article>
        </div>
      </section>
    );
  }

  if (family.family === "FORMATION_STRUCTURE") {
    return (
      <section className="hu-section hu-native-focus">
        <UniverseSectionHeading
          eyebrow="Lecture tactique"
          subtitle="Une confrontation de formations ouvre un arbre, elle ne constitue pas à elle seule une stratégie."
          title="Des structures qui se répondent"
        />
        <div className="hu-formation-example" aria-label="Exemple d’arbre tactique">
          <strong>4-4-2</strong>
          <span>contre 4-4-2</span>
          <span>contre 4-3-3</span>
          <span>contre 4-2-4</span>
          <span>contre 5-4-1</span>
          <span>contre 5-3-2</span>
        </div>
        <p className="hu-chart-summary">
          Cet exemple explique la forme de l’exploration. Les branches
          calculées restent celles du contrat et de l’index borné.
        </p>
      </section>
    );
  }

  return null;
}

export function HypothesisFamilyPage({
  family,
}: {
  family: HypothesisFamily;
}) {
  const stats = familyStats(family.family);
  const roots = familyRootNodes(family.family);
  const rankings = hypothesisRankingsByFamily[family.family] ?? {
    label_fr: family.display_name_fr,
    meilleurs_signaux_historiques_bruts: [],
    strategies_validees: [],
  };
  const prospective = hypothesisRankings.meilleures_observations_prospectives.filter(
    (entry) => entry.family === family.family,
  );
  const longTail = hypothesisRankings.longue_traine_a_surveiller.filter(
    (node) => node.family === family.family,
  );
  const registeredSubfamilies = new Set(hypothesisTags.subfamilies);
  const axes = (familyAxes[family.family] ?? [
    ...new Set(roots.map((node) => node.subfamily)),
  ]).filter((axis) => registeredSubfamilies.has(axis));
  const hasMissingData = family.availability_status !== "READY";

  return (
    <div className="hu-page hu-family-page">
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { href: "/hypotheses/familles", label: "Familles" },
          { label: family.display_name_fr },
        ]}
      />
      <HypothesisSubnav />

      <header className="hu-page-header hu-family-header">
        <div>
          <p className="hu-kicker">Famille du registre scientifique</p>
          <span className="hu-family-symbol" aria-hidden="true">
            {familyIcon(family.family)}
          </span>
          <h1>{family.display_name_fr}</h1>
          <p>{familyDescription(family)}</p>
          <div className="hu-tag-list">
            <ScientificStatusBadge status={family.availability_status} />
            {axes.slice(0, 4).map((axis) => (
              <TagChip key={axis} tagId={`subfamily:${axis}`}>
                {presentSubfamily(axis)}
              </TagChip>
            ))}
          </div>
        </div>
        <div className="hu-detail-metrics">
          <UniverseMetric
            label="Propriétés"
            tone="teal"
            value={family.property_count}
          />
          <UniverseMetric
            label="Branches matérialisées"
            tone="blue"
            value={stats.materialized}
          />
          <UniverseMetric
            label="Branches testées"
            tone="gold"
            value={stats.executed}
          />
          <UniverseMetric
            label="Bloquées"
            tone="coral"
            value={stats.blocked}
          />
        </div>
      </header>

      <section className="hu-section">
        <UniverseSectionHeading
          subtitle="Les axes ci-dessous sont affichés seulement s’ils existent dans le catalogue de tags."
          title="Sous-familles et axes de recherche"
        />
        {axes.length ? (
          <div className="hu-axis-grid">
            {axes.map((axis) => (
              <article key={axis}>
                <span aria-hidden="true">◇</span>
                <h3>{presentSubfamily(axis)}</h3>
                <p>
                  Axe représentable dans l’ontologie. Son affichage ne signifie
                  ni qu’une donnée est disponible, ni qu’une preuve existe.
                </p>
                <ExpertOnly>
                  <code>{axis}</code>
                </ExpertOnly>
              </article>
            ))}
          </div>
        ) : (
          <HonestEmptyState title="Aucune sous-famille matérialisée">
            La famille existe dans le catalogue, mais l’index borné ne publie
            encore aucun axe détaillé pour cette campagne.
          </HonestEmptyState>
        )}
      </section>

      <section className="hu-section hu-surface">
        <UniverseSectionHeading
          subtitle="Le catalogue publie un volume et des entités, sans inventaire public artificiel."
          title="Propriétés et entités"
        />
        <div className="hu-property-overview">
          <article>
            <strong>{formatNumber(family.property_count)}</strong>
            <span>propriétés inscrites dans le registre</span>
            <ScientificStatusBadge status={family.availability_status} />
          </article>
          <div>
            {family.entities.map((entity) => (
              <article key={entity}>
                <span aria-hidden="true">□</span>
                <strong>
                  {publicEntityLabels[entity] ?? "Entité du registre"}
                </strong>
                <ExpertOnly>
                  <code>{entity}</code>
                </ExpertOnly>
              </article>
            ))}
          </div>
        </div>
        <AnalysisOnly>
          <p className="hu-chart-summary">
            Fraîcheur de l’activité contractuelle :{" "}
            {hypothesisActivity.last_activity
              ? formatDateTime(hypothesisActivity.last_activity, true)
              : "aucune activité datée"}.
          </p>
        </AnalysisOnly>
      </section>

      <NativeFamilyFocus family={family} />

      <section className="hu-section">
        <UniverseSectionHeading
          action={
            <Link
              className="hu-text-link"
              href={`/hypotheses/arbres?famille=${familySlug(family.family)}`}
            >
              Ouvrir l’explorateur →
            </Link>
          }
          subtitle="Les racines sont chargées depuis l’index contractuel; leurs enfants arrivent à la demande."
          title="Arbres principaux"
        />
        {roots.length ? (
          <div className="hu-node-collection">
            {roots.map((root) => (
              <article className="hu-root-card" key={root.node_id}>
                <div>
                  <ScientificStatusBadge
                    status={root.materialization_disposition}
                  />
                  <TagChip tagId={`subfamily:${root.subfamily}`}>
                    {presentSubfamily(root.subfamily)}
                  </TagChip>
                </div>
                <h3>{root.display_rule_fr}</h3>
                <dl>
                  <div>
                    <dt>Profondeur</dt>
                    <dd>Racine</dd>
                  </div>
                  <div>
                    <dt>Enfants indexés</dt>
                    <dd>
                      {formatNumber(
                        hypothesisChildrenByParent[root.node_id]?.length ?? 0,
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Support</dt>
                    <dd>
                      {root.support == null
                        ? "Non disponible"
                        : formatNumber(root.support)}
                    </dd>
                  </div>
                </dl>
                <Link
                  className="hu-text-link"
                  href={`/hypotheses/arbres/${encodeURIComponent(root.node_id)}`}
                >
                  Développer la racine →
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <HonestEmptyState title="Aucun arbre matérialisé">
            La famille est bien enregistrée, mais cette campagne bornée ne
            publie encore aucune racine. Robin ne fabrique pas de branche pour
            remplir l’écran.
          </HonestEmptyState>
        )}
      </section>

      <section className="hu-section hu-surface">
        <UniverseSectionHeading
          subtitle="Chaque catégorie conserve son sens scientifique."
          title="Classements de la famille"
        />
        <div className="hu-family-ranking-columns">
          <article>
            <h3>Signaux historiques bruts</h3>
            {rankings.meilleurs_signaux_historiques_bruts.length ? (
              rankings.meilleurs_signaux_historiques_bruts.map((entry) => (
                <RankingCard entry={entry} key={entry.hypothesis_id} />
              ))
            ) : (
              <p>Aucun signal historique classé dans cette famille.</p>
            )}
          </article>
          <article>
            <h3>Priorités exploratoires</h3>
            <p>
              Aucun classement familial dédié n’est publié. Les signaux bruts
              ne sont pas renommés en priorités.
            </p>
          </article>
          <article>
            <h3>Observations prospectives</h3>
            <p>
              {prospective.length
                ? `${formatNumber(prospective.length)} observation classée`
                : "Aucune observation classée pour cette famille."}
            </p>
          </article>
          <article>
            <h3>Stratégies validées</h3>
            <p>
              {rankings.strategies_validees.length
                ? `${formatNumber(rankings.strategies_validees.length)} stratégie validée`
                : "Aucune stratégie scientifiquement validée."}
            </p>
          </article>
          <article>
            <h3>Longue traîne</h3>
            <p>
              {longTail.length
                ? `${formatNumber(longTail.length)} branche rare conservée`
                : "Aucune branche rare classée pour cette famille."}
            </p>
          </article>
        </div>
      </section>

      <section className="hu-section hu-missing-data">
        <UniverseSectionHeading
          title={
            hasMissingData
              ? "Données manquantes"
              : "Disponibilité des données"
          }
        />
        <div>
          <ScientificStatusBadge status={family.availability_status} />
          <p>{familyBlockingReason(family)}</p>
          <p>
            {hasMissingData
              ? "Robin conserve cette famille dans l’univers afin de la rendre testable lorsqu’une preuve temporelle admissible sera disponible."
              : "Robin peut explorer cette famille dans le périmètre contractuel actuel, tout en conservant les limites de chaque branche visibles."}
          </p>
        </div>
      </section>

      <nav aria-label="Navigation entre familles" className="hu-family-footer-nav">
        <Link href="/hypotheses/familles">← Toutes les familles</Link>
        <Link href="/hypotheses/arbres">Explorer les arbres →</Link>
      </nav>
    </div>
  );
}
