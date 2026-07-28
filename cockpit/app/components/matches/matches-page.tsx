"use client";

import { useMemo, useState } from "react";

import { formatDate, t } from "../../i18n";
import { matches } from "../../lib/presentation";
import { EmptyState, PageHeader } from "../common/ui";
import { MatchCard } from "./match-card";

type LayoutMode = "list" | "calendar";

export function MatchesPage() {
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("soon");
  const [layout, setLayout] = useState<LayoutMode>("list");

  const dateOptions = useMemo(
    () => Array.from(new Set(matches.map((match) => match.kickoff.slice(0, 10)))),
    [],
  );
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("fr-FR");
    return matches
      .filter(
        (match) =>
          (!normalized ||
            match.home.toLocaleLowerCase("fr-FR").includes(normalized) ||
            match.away.toLocaleLowerCase("fr-FR").includes(normalized)) &&
          (date === "all" || match.kickoff.startsWith(date)) &&
          (status === "all" || match.dataStatus === status),
      )
      .sort((left, right) =>
        sort === "team"
          ? left.home.localeCompare(right.home, "fr-FR")
          : new Date(left.kickoff).getTime() - new Date(right.kickoff).getTime(),
      );
  }, [date, query, sort, status]);

  const grouped = filtered.reduce<Record<string, typeof filtered>>((groups, match) => {
    const day = match.kickoff.slice(0, 10);
    groups[day] = [...(groups[day] ?? []), match];
    return groups;
  }, {});

  return (
    <>
      <PageHeader
        eyebrow={t("matches.eyebrow")}
        subtitle={t("matches.subtitle")}
        title={t("matches.title")}
      />

      <section className="filter-panel" aria-label={t("action.filters")}>
        <label className="search-field">
          <span>{t("matches.searchLabel")}</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("matches.searchPlaceholder")}
            type="search"
            value={query}
          />
        </label>
        <label>
          <span>{t("matches.filterDate")}</span>
          <select onChange={(event) => setDate(event.target.value)} value={date}>
            <option value="all">{t("matches.allDates")}</option>
            {dateOptions.map((option) => (
              <option key={option} value={option}>
                {formatDate(`${option}T12:00:00+00:00`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{t("matches.filterStatus")}</span>
          <select onChange={(event) => setStatus(event.target.value)} value={status}>
            <option value="all">{t("matches.allStatuses")}</option>
            <option value="PARTIAL">Données partielles</option>
            <option value="WAITING_FOR_OBSERVATIONS">En attente</option>
          </select>
        </label>
        <label>
          <span>{t("matches.sort")}</span>
          <select onChange={(event) => setSort(event.target.value)} value={sort}>
            <option value="soon">{t("matches.sortSoon")}</option>
            <option value="team">{t("matches.sortTeam")}</option>
          </select>
        </label>
        <div className="layout-switch" role="group" aria-label="Disposition">
          <button
            aria-pressed={layout === "list"}
            className={layout === "list" ? "active" : ""}
            onClick={() => setLayout("list")}
            type="button"
          >
            ☷ {t("matches.viewList")}
          </button>
          <button
            aria-pressed={layout === "calendar"}
            className={layout === "calendar" ? "active" : ""}
            onClick={() => setLayout("calendar")}
            type="button"
          >
            ▦ {t("matches.viewCalendar")}
          </button>
        </div>
      </section>

      {filtered.length ? (
        layout === "list" ? (
          <section className="matches-grid" aria-live="polite">
            {filtered.map((match) => <MatchCard key={match.id} match={match} />)}
          </section>
        ) : (
          <section className="calendar-view" aria-live="polite">
            {Object.entries(grouped).map(([day, dayMatches]) => (
              <article key={day}>
                <h2>{formatDate(`${day}T12:00:00+00:00`)}</h2>
                <div>
                  {dayMatches.map((match) => <MatchCard key={match.id} match={match} />)}
                </div>
              </article>
            ))}
          </section>
        )
      ) : (
        <EmptyState
          action={
            <button
              className="secondary-button"
              onClick={() => {
                setQuery("");
                setDate("all");
                setStatus("all");
              }}
              type="button"
            >
              {t("action.reset")}
            </button>
          }
          text={t("matches.none.text")}
          title={t("matches.none.title")}
        />
      )}
    </>
  );
}
