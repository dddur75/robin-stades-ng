"use client";

import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import { formatDateTime, formatNumber, formatPercent } from "../../i18n";
import {
  familyDescription,
  familyIcon,
  familySlug,
  familyStats,
  hypothesisActivity,
  hypothesisFamilies,
  hypothesisRankingsByFamily,
  type AvailabilityStatus,
} from "../../lib/hypothesis-universe";
import {
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  ScientificStatusBadge,
  UniverseSectionHeading,
} from "./hypothesis-primitives";

const availabilityFilters: Array<{
  label: string;
  value: "ALL" | AvailabilityStatus;
}> = [
  { label: "Toutes", value: "ALL" },
  { label: "Données disponibles", value: "READY" },
  { label: "Données partielles", value: "PARTIAL" },
  { label: "Bloquées par les données", value: "DATA_GATE_BLOCKED" },
];

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("fr-FR");
}

export function HypothesisFamiliesPage() {
  const [query, setQuery] = useState("");
  const [availability, setAvailability] = useState<
    "ALL" | AvailabilityStatus
  >("ALL");
  const deferredQuery = useDeferredValue(query);

  const visibleFamilies = useMemo(() => {
    const needle = normalize(deferredQuery.trim());
    return hypothesisFamilies.filter((family) => {
      const matchesAvailability =
        availability === "ALL" ||
        family.availability_status === availability;
      const matchesQuery =
        !needle ||
        normalize(
          `${family.display_name_fr} ${familyDescription(family)} ${family.entities.join(" ")}`,
        ).includes(needle);
      return matchesAvailability && matchesQuery;
    });
  }, [availability, deferredQuery]);

  return (
    <div className="hu-page hu-families-page">
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          { label: "Familles" },
        ]}
      />
      <HypothesisSubnav />

      <header className="hu-page-header">
        <div>
          <p className="hu-kicker">Catalogue contractuel</p>
          <h1>Les grandes familles</h1>
          <p>
            Chaque famille vient du registre scientifique. Une famille
            indisponible reste visible : son blocage est une information, pas
            un échec à masquer.
          </p>
        </div>
        <div className="hu-family-total" aria-label="Nombre de familles">
          <strong>{formatNumber(hypothesisFamilies.length)}</strong>
          <span>familles accessibles</span>
        </div>
      </header>

      <section
        aria-label="Filtres des familles"
        className="hu-family-filters"
      >
        <label>
          Rechercher une famille
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Météo, gardien, formations…"
            type="search"
            value={query}
          />
        </label>
        <div aria-label="Disponibilité des données" role="group">
          {availabilityFilters.map((filter) => (
            <button
              aria-pressed={availability === filter.value}
              key={filter.value}
              onClick={() => setAvailability(filter.value)}
              type="button"
            >
              {filter.label}
            </button>
          ))}
        </div>
        <p aria-live="polite">
          {formatNumber(visibleFamilies.length)} famille
          {visibleFamilies.length > 1 ? "s" : ""} affichée
          {visibleFamilies.length > 1 ? "s" : ""}
        </p>
      </section>

      <section className="hu-section">
        <UniverseSectionHeading
          subtitle="Les volumes, statuts et classements sont lus dans les contrats bornés."
          title="Explorer le catalogue"
        />
        {visibleFamilies.length ? (
          <div className="hypothesis-family-grid">
            {visibleFamilies.map((family) => {
              const stats = familyStats(family.family);
              const ranking =
                hypothesisRankingsByFamily[family.family]
                  ?.meilleurs_signaux_historiques_bruts[0];
              return (
                <article className="hypothesis-family-card" key={family.family}>
                  <div className="hu-family-card-head">
                    <span aria-hidden="true">
                      {familyIcon(family.family)}
                    </span>
                    <ScientificStatusBadge
                      status={family.availability_status}
                    />
                  </div>
                  <h2>{family.display_name_fr}</h2>
                  <p>{familyDescription(family)}</p>
                  <dl>
                    <div>
                      <dt>Propriétés</dt>
                      <dd>{formatNumber(family.property_count)}</dd>
                    </div>
                    <div>
                      <dt>Branches matérialisées</dt>
                      <dd>{formatNumber(stats.materialized)}</dd>
                    </div>
                    <div>
                      <dt>Branches testées</dt>
                      <dd>{formatNumber(stats.executed)}</dd>
                    </div>
                    <div>
                      <dt>Bloquées</dt>
                      <dd>{formatNumber(stats.blocked)}</dd>
                    </div>
                    <div>
                      <dt>Longue traîne</dt>
                      <dd>{formatNumber(stats.longTail)}</dd>
                    </div>
                    <div>
                      <dt>Meilleur signal brut</dt>
                      <dd>
                        {ranking
                          ? formatPercent(ranking.historical_roi)
                          : "Aucun signal historique classé dans cette famille"}
                      </dd>
                    </div>
                    <div>
                      <dt>Fraîcheur de l’univers</dt>
                      <dd>
                        {hypothesisActivity.last_activity
                          ? formatDateTime(hypothesisActivity.last_activity)
                          : "Aucune activité datée"}
                      </dd>
                    </div>
                  </dl>
                  <Link
                    className="hu-primary-action"
                    href={`/hypotheses/familles/${familySlug(family.family)}`}
                  >
                    Explorer la famille
                  </Link>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="hu-empty" role="status">
            <span aria-hidden="true">○</span>
            <div>
              <h2>Aucune famille ne correspond</h2>
              <p>
                Essayez un mot plus général ou affichez toutes les
                disponibilités.
              </p>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
