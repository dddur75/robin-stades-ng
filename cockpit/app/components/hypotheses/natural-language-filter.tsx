"use client";

import { useEffect, useId, useMemo, useState } from "react";

import {
  hypothesisFamilies,
} from "../../lib/hypothesis-universe";
import {
  parseFrenchHypothesisQuery,
  type UnderstoodFilter,
} from "../../lib/hypothesis-filter";
import { TagChip } from "./hypothesis-primitives";

type SavedView = {
  filters: UnderstoodFilter[];
  query: string;
};

const favoriteStorageKey = "robin-hypothesis-favorite-views-v1";

function readSavedViews(): SavedView[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(favoriteStorageKey) ?? "[]",
    ) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is SavedView =>
          typeof item === "object" &&
          item !== null &&
          typeof (item as SavedView).query === "string" &&
          Array.isArray((item as SavedView).filters),
      )
      .slice(0, 8);
  } catch {
    return [];
  }
}

export function NaturalLanguageFilter({
  initialQuery = "",
  onChange,
}: {
  initialQuery?: string;
  onChange: (filters: UnderstoodFilter[], query: string) => void;
}) {
  const inputId = useId();
  const [query, setQuery] = useState(initialQuery);
  const [understood, setUnderstood] = useState<UnderstoodFilter[]>(() =>
    parseFrenchHypothesisQuery(initialQuery),
  );
  const [favoriteMessage, setFavoriteMessage] = useState("");
  const [savedViews, setSavedViews] = useState<SavedView[]>([]);
  const examples = useMemo(
    () => [
      "Météo ET vent fort ET gardien ET centres",
      "Liga ET plus de 200 matchs SAUF branches bloquées",
      "Troisième déplacement OU fatigue",
    ],
    [],
  );

  useEffect(() => {
    onChange(understood, query);
  }, [onChange, query, understood]);

  useEffect(() => {
    queueMicrotask(() => setSavedViews(readSavedViews()));
  }, []);

  const interpret = () => {
    const next = parseFrenchHypothesisQuery(query);
    setUnderstood(next);
    const url = new URL(window.location.href);
    if (query.trim()) url.searchParams.set("q", query.trim());
    else url.searchParams.delete("q");
    window.history.replaceState({}, "", url);
  };

  const saveView = () => {
    const next = [
      { filters: understood, query },
      ...savedViews.filter((item) => item.query !== query),
    ].slice(0, 8);
    window.localStorage.setItem(favoriteStorageKey, JSON.stringify(next));
    setSavedViews(next);
    setFavoriteMessage("Vue enregistrée sur cet appareil.");
  };

  const removeSavedView = (savedQuery: string) => {
    const next = savedViews.filter((item) => item.query !== savedQuery);
    window.localStorage.setItem(favoriteStorageKey, JSON.stringify(next));
    setSavedViews(next);
    setFavoriteMessage("Vue supprimée de cet appareil.");
  };

  return (
    <section className="hu-natural-filter" aria-labelledby={`${inputId}-title`}>
      <div>
        <p className="hu-kicker">Recherche guidée en français</p>
        <h2 id={`${inputId}-title`}>Décrivez ce que vous cherchez</h2>
        <p>
          L’analyse est locale et déterministe. Aucun modèle externe n’est
          appelé et Robin n’invente aucune valeur.
        </p>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          interpret();
        }}
      >
        <label htmlFor={inputId}>Votre recherche</label>
        <div className="hu-search-row">
          <input
            id={inputId}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Météo ET vent fort SAUF branches bloquées"
            type="search"
            value={query}
          />
          <button className="hu-primary-action" type="submit">
            Traduire en filtres
          </button>
        </div>
      </form>
      <div className="hu-query-examples" aria-label="Exemples de recherche">
        {examples.map((example) => (
          <button
            key={example}
            onClick={() => {
              setQuery(example);
              setUnderstood(parseFrenchHypothesisQuery(example));
            }}
            type="button"
          >
            {example}
          </button>
        ))}
      </div>
      <div className="hu-understood-filters" aria-live="polite">
        <div>
          <strong>Filtres compris par Robin</strong>
          <span>
            {understood.length
              ? understood
                  .map((filter) => `${filter.operator} ${filter.label}`)
                  .join(" ")
                  .replace(/^ET /, "")
              : "Aucun filtre reconnu"}
          </span>
        </div>
        <div className="hu-tag-list">
          {understood.map((filter) => (
            <TagChip
              kind={filter.operator === "SAUF" ? "science" : "family"}
              key={filter.id}
            >
              {filter.operator} {filter.label}
            </TagChip>
          ))}
        </div>
        <div className="hu-filter-actions">
          <button
            disabled={!understood.length}
            onClick={saveView}
            type="button"
          >
            Enregistrer cette vue
          </button>
          <button
            onClick={() => {
              setQuery("");
              setUnderstood([]);
              const url = new URL(window.location.href);
              url.searchParams.delete("q");
              window.history.replaceState({}, "", url);
            }}
            type="button"
          >
            Réinitialiser
          </button>
          {favoriteMessage ? <span role="status">{favoriteMessage}</span> : null}
        </div>
      </div>
      {savedViews.length ? (
        <details className="hu-saved-views">
          <summary>Vues enregistrées sur cet appareil ({savedViews.length})</summary>
          <ul>
            {savedViews.map((view) => (
              <li key={view.query}>
                <button
                  onClick={() => {
                    setQuery(view.query);
                    setUnderstood(parseFrenchHypothesisQuery(view.query));
                    const url = new URL(window.location.href);
                    url.searchParams.set("q", view.query);
                    window.history.replaceState({}, "", url);
                    setFavoriteMessage("Vue restaurée.");
                  }}
                  type="button"
                >
                  <strong>{view.query}</strong>
                  <span>Restaurer</span>
                </button>
                <button
                  aria-label={`Supprimer la vue ${view.query}`}
                  onClick={() => removeSavedView(view.query)}
                  type="button"
                >
                  Supprimer
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <details className="hu-guided-facets">
        <summary>Ajouter une famille sans écrire de phrase</summary>
        <div>
          {hypothesisFamilies.map((family) => (
            <button
              key={family.family}
              onClick={() => {
                const phrase = query.trim()
                  ? `${query.trim()} ET ${family.display_name_fr}`
                  : family.display_name_fr;
                const familyFilter: UnderstoodFilter = {
                  field: "family",
                  id: `family:${family.family}`,
                  label: family.display_name_fr,
                  operator: "ET",
                  segment:
                    understood.reduce(
                      (maximum, item) => Math.max(maximum, item.segment),
                      -1,
                    ) + 1,
                  value: family.family,
                };
                setQuery(phrase);
                setUnderstood((current) => [
                  ...current.filter((item) => item.id !== familyFilter.id),
                  familyFilter,
                ]);
              }}
              title={`Filtrer sur ${family.display_name_fr}`}
              type="button"
            >
              {family.display_name_fr}
            </button>
          ))}
        </div>
      </details>
    </section>
  );
}
