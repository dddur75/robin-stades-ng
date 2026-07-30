import Link from "next/link";

import { Pagination } from "../common/pagination";
import { ExpertOnly } from "../common/view-mode";
import {
  HypothesisBreadcrumbs,
  HypothesisSubnav,
} from "./hypothesis-primitives";
import type { HistoricalMatchListPageData } from "../../lib/historical-match-evidence.server";
import {
  historicalFoldLabel,
  historicalMatchDetailPath,
  historicalMatchListPath,
  serializeHistoricalMatchListQuery,
  type HistoricalMatchListQuery,
  type HistoricalMatchListRow,
} from "../../lib/historical-match-evidence";
import styles from "./hypothesis-historical-matches-page.module.css";

const dateFormatter = new Intl.DateTimeFormat("fr-FR", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/Paris",
});
const numberFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});
const percentFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  style: "percent",
});
const signedFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  signDisplay: "always",
});

const outcomeLabels = {
  lost: "Perdu",
  void: "Annulé",
  won: "Gagné",
} as const;

const selectionLabels: Record<string, string> = {
  AWAY: "Victoire extérieure",
  DRAW: "Match nul",
  HOME: "Victoire domicile",
};

function selectionLabel(value: string): string {
  return selectionLabels[value] ?? "Sélection historique documentée";
}

function SelectionValue({ value }: { value: string }) {
  return (
    <>
      {selectionLabel(value)}
      <ExpertOnly>
        {" "}
        <code>{value}</code>
      </ExpertOnly>
    </>
  );
}

function FoldValue({ value }: { value: string }) {
  return (
    <>
      {historicalFoldLabel(value)}
      <ExpertOnly>
        {" "}
        <code>{value}</code>
      </ExpertOnly>
    </>
  );
}

function formatUnits(value: number): string {
  return `${signedFormatter.format(value)} ${
    Math.abs(value) === 1 ? "unité" : "unités"
  }`;
}

function outcomeBadge(row: HistoricalMatchListRow) {
  return (
    <span
      className={`${styles.outcome} ${styles[row.outcome]}`}
      data-outcome={row.outcome}
    >
      {outcomeLabels[row.outcome]}
    </span>
  );
}

function profitClass(value: number): string {
  return value >= 0 ? styles.positive : styles.negative;
}

function score(row: HistoricalMatchListRow): string {
  return `${row.fixture.finalScore.home} – ${row.fixture.finalScore.away}`;
}

function matchLabel(row: HistoricalMatchListRow): string {
  return `${row.fixture.homeTeam.name} – ${row.fixture.awayTeam.name}`;
}

function MatchCard({
  detailHref,
  row,
}: {
  detailHref: string;
  row: HistoricalMatchListRow;
}) {
  return (
    <Link
      aria-label={`Ouvrir la preuve historique de ${matchLabel(row)}`}
      className={styles.cardLink}
      href={detailHref}
    >
      <article className={styles.card}>
        <header className={styles.cardHeader}>
          <div>
            <p>
              <time dateTime={row.fixture.kickoffAt}>
                {dateFormatter.format(new Date(row.fixture.kickoffAt))}
              </time>
              {" · "}
              {row.fixture.competition}
            </p>
            <h3>{matchLabel(row)}</h3>
          </div>
          <span
            aria-label={`Score final ${score(row)}`}
            className={styles.cardScore}
          >
            {score(row)}
          </span>
        </header>
        <dl>
          <div>
            <dt>Saison</dt>
            <dd>{row.fixture.season}</dd>
          </div>
          <div>
            <dt>Sélection</dt>
            <dd>
              <SelectionValue value={row.selection} />
            </dd>
          </div>
          <div>
            <dt>Cote · marge</dt>
            <dd>
              {numberFormatter.format(row.observedOdds)}
              {" · "}
              {percentFormatter.format(row.marketMargin)}
            </dd>
          </div>
          <div>
            <dt>Résultat</dt>
            <dd>{outcomeBadge(row)}</dd>
          </div>
          <div>
            <dt>Profit</dt>
            <dd className={profitClass(row.profitUnits)}>
              {formatUnits(row.profitUnits)}
            </dd>
          </div>
          <div>
            <dt>Profit cumulé</dt>
            <dd className={profitClass(row.cumulativeProfitUnits)}>
              {formatUnits(row.cumulativeProfitUnits)}
            </dd>
          </div>
          <div>
            <dt>Période chronologique</dt>
            <dd>
              <FoldValue value={row.chronologicalFold} />
            </dd>
          </div>
        </dl>
        <span className={styles.matchLink}>
          Ouvrir la fiche du match
          <span aria-hidden="true"> →</span>
        </span>
      </article>
    </Link>
  );
}

export function HypothesisHistoricalMatchesPage({
  data,
  query,
}: {
  data: HistoricalMatchListPageData;
  query: HistoricalMatchListQuery;
}) {
  const hypothesisId = data.hypothesis.hypothesisId;
  const pathname = historicalMatchListPath(hypothesisId);
  const effectiveQuery = {
    ...query,
    page: data.pagination.page,
  };
  const currentListPath = historicalMatchListPath(
    hypothesisId,
    effectiveQuery,
  );
  const canonicalSearch = serializeHistoricalMatchListQuery(effectiveQuery);

  return (
    <div className={`hu-page ${styles.page}`}>
      <HypothesisBreadcrumbs
        items={[
          { href: "/robin-live", label: "Accueil" },
          { href: "/hypotheses", label: "Hypothèses" },
          {
            href: `/hypotheses/${hypothesisId}`,
            label: hypothesisId,
          },
          { label: "Matchs historiques" },
        ]}
      />
      <HypothesisSubnav />

      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>
            Preuves historiques · données gelées
          </p>
          <h1>Matchs de {hypothesisId}</h1>
          <p>
            Chaque ligne correspond à une appartenance reconstruite depuis
            les données historiques gelées. Les cotes, scores et profits ne
            sont jamais complétés par l’interface.
          </p>
          <div className={styles.heroMeta}>
            <span className={styles.historicalBadge}>
              Simulation historique uniquement
            </span>
            <span>{data.sourceTotalItems} occurrences historiques</span>
            <span>
              {data.hypothesis.rank === null
                ? "Hors du top 10 global par ROI historique brut"
                : `Rang par ROI historique brut #${data.hypothesis.rank}`}
            </span>
            <span>{data.conditions.length} conditions de règle</span>
          </div>
        </div>
        <nav aria-label="Raccourcis de l’hypothèse" className={styles.heroActions}>
          <Link href={`/hypotheses/${hypothesisId}`}>
            Revenir à la fiche
          </Link>
          <Link href="/hypotheses/classements">
            Voir les classements
          </Link>
        </nav>
      </header>

      <aside className={styles.historicalNotice}>
        <span aria-hidden="true">H</span>
        <div>
          <strong>Historique et prospectif restent séparés.</strong>
          Ces matchs déjà joués sont des simulations historiques. Ils ne sont
          ni des observations depuis le gel, ni des paris réels, ni une
          promesse de performance future.
        </div>
      </aside>

      <section
        aria-labelledby="historical-match-filters"
        className={styles.panel}
      >
        <div className={styles.panelHeading}>
          <div>
            <h2 id="historical-match-filters">Filtrer les preuves</h2>
            <p>
              Les filtres et tris sont appliqués côté serveur avant de rendre
              une page de 25 ou 50 résultats.
            </p>
          </div>
        </div>
        <form
          action={pathname}
          aria-describedby="historical-filter-help"
          className={styles.filters}
          method="get"
        >
          <label>
            Saison
            <input
              defaultValue={query.season ?? ""}
              inputMode="numeric"
              maxLength={120}
              name="saison"
              placeholder="Ex. 2023"
            />
          </label>
          <label>
            Équipe
            <input
              defaultValue={query.team}
              maxLength={120}
              name="equipe"
              placeholder="Nom de l’équipe"
              type="search"
            />
          </label>
          <label>
            Résultat
            <select defaultValue={query.outcome} name="resultat">
              <option value="all">Tous</option>
              <option value="won">Gagné</option>
              <option value="lost">Perdu</option>
              <option value="void">Annulé</option>
            </select>
          </label>
          <label>
            Sélection
            <select defaultValue={query.selection} name="selection">
              <option value="all">Toutes</option>
              <option value="HOME">Victoire domicile</option>
              <option value="DRAW">Match nul</option>
              <option value="AWAY">Victoire extérieure</option>
            </select>
          </label>
          <label>
            Bande de cote
            <select defaultValue={query.oddsBand} name="cotes">
              <option value="all">Toutes les cotes</option>
              <option value="under-1.60">Moins de 1,60</option>
              <option value="1.60-2.00">1,60 à moins de 2,00</option>
              <option value="2.00-2.50">2,00 à moins de 2,50</option>
              <option value="2.50-3.25">2,50 à 3,25</option>
              <option value="over-3.25">Plus de 3,25</option>
            </select>
          </label>
          <label>
            Période chronologique
            <input
              defaultValue={
                query.fold === null ? "" : historicalFoldLabel(query.fold)
              }
              maxLength={120}
              name="periode"
              placeholder="Ex. Saison 2023"
            />
          </label>
          <label>
            Trier par
            <select defaultValue={query.sort} name="tri">
              <option value="date-asc">Date · ancienne à récente</option>
              <option value="date-desc">Date · récente à ancienne</option>
              <option value="odds-asc">Cote · croissante</option>
              <option value="odds-desc">Cote · décroissante</option>
              <option value="profit-desc">Profit · décroissant</option>
              <option value="profit-asc">Profit · croissant</option>
              <option value="outcome">Résultat · gagnés d’abord</option>
            </select>
          </label>
          <label>
            Résultats par page
            <select defaultValue={String(query.pageSize)} name="taille">
              <option value="25">25</option>
              <option value="50">50</option>
            </select>
          </label>
          <div className={styles.filterActions}>
            <button type="submit">Appliquer les filtres</button>
            <Link href={pathname}>Réinitialiser</Link>
          </div>
        </form>
        <p className={styles.filterHelp} id="historical-filter-help">
          Une nouvelle recherche repart automatiquement à la première page.
          Seuls les 25 ou 50 résultats de la page demandée sont transmis à
          l’écran.
          <ExpertOnly>
            {" "}
            L’index serveur est plafonné à {data.scan.maximumItems}{" "}
            appartenances.
          </ExpertOnly>
        </p>
      </section>

      <section
        aria-labelledby="historical-match-results"
        className={styles.panel}
      >
        <div className={styles.panelHeading}>
          <div>
            <h2 id="historical-match-results">Matchs correspondants</h2>
            <p aria-live="polite">
              {data.pagination.totalItems === 0
                ? "Aucun match ne correspond aux filtres."
                : `${data.pagination.from} à ${data.pagination.to} sur ${data.pagination.totalItems} résultat${data.pagination.totalItems > 1 ? "s" : ""}.`}
            </p>
          </div>
          <div className={styles.resultMeta}>
            <span>Résultats filtrés avant affichage</span>
            <ExpertOnly>
              <span>
                {data.scan.mode === "query-index"
                  ? `Index serveur compact · ${data.scan.assetsLoaded} source chargée`
                  : `Lecture chronologique · ${data.scan.assetsLoaded} fragment${data.scan.assetsLoaded > 1 ? "s" : ""}`}
              </span>
            </ExpertOnly>
            <span>25/50 maximum par réponse</span>
          </div>
        </div>

        {data.rows.length === 0 ? (
          <div className={styles.empty}>
            <div>
              <h3>Aucune preuve dans ce périmètre</h3>
              <p>
                Les filtres n’ont produit aucun résultat. Robin n’ajoute aucun
                match de remplacement et conserve les données sources intactes.
              </p>
            </div>
          </div>
        ) : (
          <>
            <div
              aria-label="Tableau des matchs historiques"
              className={styles.tableRegion}
              role="region"
              tabIndex={0}
            >
              <table className={styles.table}>
                <caption className={styles.srOnly}>
                  Matchs historiques appartenant à l’hypothèse {hypothesisId}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Saison</th>
                    <th scope="col">Championnat</th>
                    <th scope="col">Match</th>
                    <th scope="col">Sélection</th>
                    <th scope="col">Cote</th>
                    <th scope="col">Marge</th>
                    <th scope="col">Score</th>
                    <th scope="col">Résultat</th>
                    <th scope="col">Profit</th>
                    <th scope="col">Profit cumulé</th>
                    <th scope="col">Période chronologique</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => {
                    const detailHref = historicalMatchDetailPath(
                      row.canonicalMatchId,
                      {
                        hypothesisId,
                        returnTo: currentListPath,
                      },
                    );
                    return (
                      <tr key={row.canonicalMatchId}>
                        <td>
                          <time dateTime={row.fixture.kickoffAt}>
                            {dateFormatter.format(
                              new Date(row.fixture.kickoffAt),
                            )}
                          </time>
                        </td>
                        <td>{row.fixture.season}</td>
                        <td>{row.fixture.competition}</td>
                        <td>
                          <Link
                            aria-label={`Ouvrir la preuve historique de ${matchLabel(row)}`}
                            className={styles.rowLink}
                            href={detailHref}
                          >
                            {matchLabel(row)}
                          </Link>
                        </td>
                        <td>
                          <SelectionValue value={row.selection} />
                        </td>
                        <td className={styles.number}>
                          {numberFormatter.format(row.observedOdds)}
                        </td>
                        <td className={styles.number}>
                          {percentFormatter.format(row.marketMargin)}
                        </td>
                        <td className={styles.score}>{score(row)}</td>
                        <td>{outcomeBadge(row)}</td>
                        <td
                          className={`${styles.number} ${profitClass(row.profitUnits)}`}
                        >
                          {formatUnits(row.profitUnits)}
                        </td>
                        <td
                          className={`${styles.number} ${profitClass(row.cumulativeProfitUnits)}`}
                        >
                          {formatUnits(row.cumulativeProfitUnits)}
                        </td>
                        <td>
                          <FoldValue value={row.chronologicalFold} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className={styles.cards}>
              {data.rows.map((row) => (
                <MatchCard
                  detailHref={historicalMatchDetailPath(
                    row.canonicalMatchId,
                    {
                      hypothesisId,
                      returnTo: currentListPath,
                    },
                  )}
                  key={row.canonicalMatchId}
                  row={row}
                />
              ))}
            </div>
          </>
        )}

        <div className={styles.paginationWrap}>
          <Pagination
            ariaLabel={`Pagination des matchs historiques de ${hypothesisId}`}
            pagination={data.pagination}
            pathname={pathname}
            searchParams={canonicalSearch}
          />
        </div>
      </section>
    </div>
  );
}
