"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  startTransition,
  useEffect,
  useState,
} from "react";

import type {
  HistoricalEvidenceFilterOption,
  HistoricalEvidenceRankingPage,
  HistoricalEvidenceSort,
} from "../../lib/hypothesis-evidence.server";
import { useViewMode } from "../common/view-mode";

const sortOptions: ReadonlyArray<{
  label: string;
  value: HistoricalEvidenceSort;
}> = [
  { label: "ROI historique brut", value: "roi-desc" },
  { label: "Profit simulé", value: "profit-desc" },
  { label: "Nombre de matchs observés", value: "support-desc" },
  { label: "Taux de réussite", value: "hit-rate-desc" },
  { label: "Baisse maximale la plus faible", value: "drawdown-asc" },
];

function FilterSelect({
  allLabel,
  label,
  name,
  onChange,
  options,
  value,
}: {
  allLabel: string;
  label: string;
  name: string;
  onChange: (value: string) => void;
  options: readonly HistoricalEvidenceFilterOption[];
  value: string;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        name={name}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function HistoricalEvidenceModeIntro() {
  const { mode } = useViewMode();
  return (
    <section
      aria-label={`Lecture ${
        mode === "discovery"
          ? "Découverte"
          : mode === "analysis"
            ? "Analyse"
            : "Expert"
      }`}
      className="hu-section hu-surface hu-mode-summary"
      data-view-mode={mode}
    >
      <p className="hu-kicker">
        Vue{" "}
        {mode === "discovery"
          ? "Découverte"
          : mode === "analysis"
            ? "Analyse"
            : "Expert"}
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
          ? "Ces signaux viennent de matchs déjà joués. Leur classement aide à les explorer, sans les transformer en stratégies validées."
          : mode === "analysis"
            ? "Chaque rang reste accompagné de son nombre d’occurrences, de son risque corrigé et de sa baisse historique simulée."
            : "La preuve compacte conserve les hashes, la révision source et la règle de départage nécessaires à l’audit."}
      </p>
    </section>
  );
}

export function HistoricalEvidenceRankingControls({
  page,
}: {
  page: HistoricalEvidenceRankingPage;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!pending) return;
    const timeout = window.setTimeout(() => setPending(false), 1_500);
    return () => window.clearTimeout(timeout);
  }, [pending, page]);

  const replaceParameter = (name: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    next.delete("page");
    const query = next.toString();
    setPending(true);
    startTransition(() => {
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    });
  };

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams.toString());
    for (const name of [
      "competition",
      "famille",
      "marche",
      "origine",
      "heure-limite",
      "page",
    ]) {
      next.delete(name);
    }
    const query = next.toString();
    setPending(true);
    startTransition(() => {
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    });
  };

  const activeCompetition = page.activeFilters.competition ?? "";

  return (
    <form
      action={pathname}
      aria-label="Portée et tri du classement historique"
      className="hu-ranking-filters"
      method="get"
    >
      <fieldset className="hu-league-tabs">
        <legend className="sr-only">Championnat</legend>
        <button
          aria-pressed={!activeCompetition}
          onClick={() => replaceParameter("competition", "")}
          type="button"
        >
          Global
        </button>
        {page.filters.competitions.map((option) => (
          <button
            aria-pressed={activeCompetition === option.value}
            key={option.value}
            onClick={() =>
              replaceParameter("competition", option.value)
            }
            type="button"
          >
            {option.label}
          </button>
        ))}
      </fieldset>

      <div className="hu-ranking-filter-fields">
        <FilterSelect
          allLabel="Toutes les familles"
          label="Famille"
          name="famille"
          onChange={(value) => replaceParameter("famille", value)}
          options={page.filters.families}
          value={page.activeFilters.family ?? ""}
        />
        <FilterSelect
          allLabel="Tous les marchés documentés"
          label="Marché"
          name="marche"
          onChange={(value) => replaceParameter("marche", value)}
          options={page.filters.markets}
          value={page.activeFilters.market ?? ""}
        />
        <FilterSelect
          allLabel="Toutes les origines documentées"
          label="Origine"
          name="origine"
          onChange={(value) => replaceParameter("origine", value)}
          options={page.filters.origins}
          value={page.activeFilters.origin ?? ""}
        />
        <FilterSelect
          allLabel="Toutes les disponibilités temporelles"
          label="Heure limite"
          name="heure-limite"
          onChange={(value) =>
            replaceParameter("heure-limite", value)
          }
          options={page.filters.cutoffs}
          value={page.activeFilters.cutoff ?? ""}
        />
        <label>
          Trier par
          <select
            aria-label="Trier par"
            name="tri"
            onChange={(event) =>
              replaceParameter("tri", event.target.value)
            }
            value={page.sort}
          >
            {sortOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="hu-ranking-filter-actions">
        <button onClick={clearFilters} type="button">
          Effacer les filtres
        </button>
        <noscript>
          <button type="submit">Appliquer les filtres</button>
        </noscript>
      </div>
      <p aria-live="polite" className="hu-ranking-join-state">
        {pending
          ? "Mise à jour du classement…"
          : `${page.items.length} signal${
              page.items.length > 1 ? "aux chargés" : " chargé"
            }, limite serveur ${page.boundedItemLimit}.`}
      </p>
    </form>
  );
}
