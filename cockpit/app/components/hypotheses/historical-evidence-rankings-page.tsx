import Link from "next/link";

import { formatNumber } from "../../i18n";
import {
  formatEvidenceNumber,
  formatEvidencePercent,
  formatEvidenceUnits,
} from "../../lib/hypothesis-evidence-format";
import type {
  HistoricalEvidenceRankingEntry,
  HistoricalEvidenceRankingPage,
  HistoricalEvidenceReportSummary,
} from "../../lib/hypothesis-evidence.server";
import { Pagination } from "../common/pagination";
import { AnalysisOnly, ExpertOnly } from "../common/view-mode";
import {
  HonestEmptyState,
  HypothesisBreadcrumbs,
  HypothesisSubnav,
  MetricExplainer,
  ScientificStatusBadge,
  TagChip,
  UniverseMetric,
  UniverseSectionHeading,
} from "./hypothesis-primitives";
import {
  HistoricalEvidenceModeIntro,
  HistoricalEvidenceRankingControls,
} from "./historical-evidence-ranking-controls";

function selectionLabel(selection: string) {
  const labels: Record<string, string> = {
    AWAY: "Victoire à l’extérieur",
    DRAW: "Match nul",
    HOME: "Victoire à domicile",
  };
  return labels[selection] ?? "Sélection documentée";
}

function marketLabel(market: string) {
  const labels: Record<string, string> = {
    "1X2_AWAY": "Résultat du match · extérieur",
    "1X2_DRAW": "Résultat du match · nul",
    "1X2_HOME": "Résultat du match · domicile",
  };
  return labels[market] ?? "Marché documenté";
}

function sortLabel(sort: HistoricalEvidenceRankingPage["sort"]) {
  const labels: Record<HistoricalEvidenceRankingPage["sort"], string> = {
    "drawdown-asc": "baisse maximale croissante",
    "hit-rate-desc": "taux de réussite décroissant",
    "profit-desc": "profit simulé décroissant",
    "roi-desc": "ROI historique brut décroissant",
    "support-desc": "nombre de matchs décroissant",
  };
  return labels[sort];
}

export function HistoricalRankingAnalysisMetrics({
  entry,
}: {
  entry: HistoricalEvidenceRankingEntry;
}) {
  const stability =
    entry.evidence.phase === "historical"
      ? entry.evidence.stability
      : null;
  return (
    <>
      <div>
        <dt>Cote moyenne</dt>
        <dd>{formatEvidenceNumber(entry.metrics.averageOdds)}</dd>
      </div>
      <div>
        <dt>Intervalle historique</dt>
        <dd>
          {formatEvidencePercent(
            entry.metrics.confidenceInterval[0],
            true,
          )}{" "}
          à{" "}
          {formatEvidencePercent(
            entry.metrics.confidenceInterval[1],
            true,
          )}
        </dd>
      </div>
      <div>
        <dt>Périodes positives</dt>
        <dd>
          {entry.metrics.positiveFolds}/{entry.metrics.eligibleFolds}
        </dd>
      </div>
      <div>
        <dt>Baisse maximale</dt>
        <dd>
          {formatEvidenceUnits(entry.metrics.maximumDrawdownUnits)}
        </dd>
      </div>
      <div>
        <dt>Risque de faux positif après correction</dt>
        <dd>
          {formatEvidenceNumber(
            entry.metrics.correctedFalsePositiveRisk,
          )}
        </dd>
      </div>
      <div>
        <dt>Stabilité hors échantillon</dt>
        <dd>
          {stability == null
            ? "Non disponible dans le classement compact"
            : formatEvidencePercent(stability)}
        </dd>
      </div>
      <div>
        <dt>Concentration</dt>
        <dd>Non disponible dans le classement compact</dd>
      </div>
    </>
  );
}

export function HistoricalRankingCard({
  entry,
}: {
  entry: HistoricalEvidenceRankingEntry;
}) {
  return (
    <article
      aria-labelledby={`ranking-${entry.hypothesisId}`}
      className="hu-ranking-card hu-evidence-ranking-card"
    >
      <div className="hu-ranking-card-head">
        <span className="hu-rank">#{entry.rank}</span>
        <ScientificStatusBadge status={entry.scientificStatus} />
      </div>
      <h3 id={`ranking-${entry.hypothesisId}`}>{entry.labelFr}</h3>
      <p className="hu-kicker">{entry.hypothesisId}</p>
      <div className="hu-tag-list">
        <TagChip kind="family">
          {entry.competition ?? "Tous championnats disponibles"}
        </TagChip>
        <TagChip kind="value">
          {selectionLabel(entry.selection)}
        </TagChip>
      </div>
      <dl>
        <div>
          <dt>Marché</dt>
          <dd>{marketLabel(entry.market ?? "")}</dd>
        </div>
        <div>
          <dt>Occurrences historiques</dt>
          <dd>{formatNumber(entry.metrics.occurrences)}</dd>
        </div>
        <div>
          <dt>ROI historique brut</dt>
          <dd>{formatEvidencePercent(entry.metrics.roi, true)}</dd>
        </div>
        <div>
          <dt>Profit simulé</dt>
          <dd>{formatEvidenceUnits(entry.metrics.profitUnits, true)}</dd>
        </div>
        <div>
          <dt>Gagnés / perdus / annulés</dt>
          <dd>
            {formatNumber(entry.metrics.wins)} /{" "}
            {formatNumber(entry.metrics.losses)} /{" "}
            {formatNumber(entry.metrics.voids)}
          </dd>
        </div>
        <div>
          <dt>Taux de réussite</dt>
          <dd>{formatEvidencePercent(entry.metrics.hitRate)}</dd>
        </div>
        <AnalysisOnly>
          <HistoricalRankingAnalysisMetrics entry={entry} />
        </AnalysisOnly>
      </dl>
      <Link
        className="hu-text-link"
        href={`/hypotheses/${encodeURIComponent(entry.hypothesisId)}`}
      >
        Ouvrir la fiche
        <span aria-hidden="true"> →</span>
      </Link>
    </article>
  );
}

function EvidenceComparisonTable({
  entries,
}: {
  entries: readonly HistoricalEvidenceRankingEntry[];
}) {
  return (
    <div
      aria-label="Tableau comparatif des preuves historiques"
      className="hu-evidence-table-wrap"
      role="region"
      tabIndex={0}
    >
      <table className="hu-evidence-table">
        <caption>
          Mesures exactes des lignes chargées, triées côté serveur.
        </caption>
        <thead>
          <tr>
            <th scope="col">Rang</th>
            <th scope="col">Hypothèse</th>
            <th scope="col">Occurrences historiques</th>
            <th scope="col">Résultat brut</th>
            <th scope="col">Profit simulé</th>
            <th scope="col">Baisse maximale</th>
            <th scope="col">Périodes positives</th>
            <th scope="col">Risque corrigé</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.hypothesisId}>
              <td>{entry.rank}</td>
              <th scope="row">
                <Link href={`/hypotheses/${entry.hypothesisId}`}>
                  {entry.hypothesisId}
                </Link>
              </th>
              <td>{formatNumber(entry.metrics.occurrences)}</td>
              <td>{formatEvidencePercent(entry.metrics.roi, true)}</td>
              <td>{formatEvidenceUnits(entry.metrics.profitUnits, true)}</td>
              <td>
                {formatEvidenceUnits(
                  entry.metrics.maximumDrawdownUnits,
                )}
              </td>
              <td>
                {entry.metrics.positiveFolds}/
                {entry.metrics.eligibleFolds}
              </td>
              <td>
                {formatEvidenceNumber(
                  entry.metrics.correctedFalsePositiveRisk,
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoricalEvidenceRankingsPage({
  canonicalSearchParams,
  page,
  summary,
}: {
  canonicalSearchParams: string;
  page: HistoricalEvidenceRankingPage;
  summary: HistoricalEvidenceReportSummary;
}) {
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
          <p className="hu-kicker">Preuve Jalon 10 réconciliée</p>
          <h1>Classements des hypothèses</h1>
          <p>
            Les rangs ci-dessous utilisent uniquement le rapport historique
            compact. Ils ne mélangent ni observation prospective, ni stratégie
            validée, ni donnée inventée.
          </p>
        </div>
        <UniverseMetric
          detail={`${formatNumber(summary.fixtures)} matchs sources`}
          label="Règles historiques réconciliées"
          tone="blue"
          value={summary.rules}
        />
      </header>

      <HistoricalEvidenceModeIntro />
      <HistoricalEvidenceRankingControls page={page} />

      <section aria-labelledby="historical-ranking-title" className="hu-section">
        <UniverseSectionHeading
          eyebrow="Simulation historique"
          subtitle={`Top ${page.requestedTop} borné · ${sortLabel(page.sort)}.`}
          title="Meilleurs signaux historiques bruts"
        />
        <p className="hu-evidence-warning" role="note">
          {page.reportWarning}
        </p>
        <div className="hu-evidence-ranking-meta">
          <p aria-live="polite">
            {page.items.length
              ? `${page.items.length} ligne${
                  page.items.length > 1 ? "s" : ""
                } affichée${
                  page.items.length > 1 ? "s" : ""
                } sur ${formatNumber(page.availableCount)} ensemble${
                  page.availableCount > 1 ? "s" : ""
                } disponible${
                  page.availableCount > 1 ? "s" : ""
                } dans cette portée.`
              : "Aucune ligne ne correspond à cette portée bornée."}
          </p>
          <p>
            {page.selectionIsCompleteForRequestedTop
              ? "Le nombre demandé est atteint ; les égalités suivent un ordre stable et déterministe."
              : "La source fournit moins de dix lignes ou le filtre est appliqué à une projection compacte : Robin n’extrapole pas les lignes absentes."}
            <ExpertOnly>
              {page.selectionIsCompleteForRequestedTop
                ? " En Vue Expert, le hash de règle documente le départage."
                : null}
            </ExpertOnly>
          </p>
        </div>

        {page.items.length ? (
          <div className="hu-ranking-grid">
            {page.items.map((entry) => (
              <HistoricalRankingCard
                entry={entry}
                key={entry.hypothesisId}
              />
            ))}
          </div>
        ) : (
          <HonestEmptyState
            title={
              page.activeFilters.family
                ? "Aucun signal historique classé dans cette famille"
                : "Aucun signal historique classé"
            }
          >
            Le rapport borné ne publie aucune ligne pour ces filtres. Cette
            absence ne prouve pas que la famille ou le championnat est sans
            intérêt.
          </HonestEmptyState>
        )}

        <Pagination
          ariaLabel="Pagination du classement historique"
          pagination={page.pagination}
          pathname="/hypotheses/classements"
          searchParams={new URLSearchParams(canonicalSearchParams)}
        />
      </section>

      <AnalysisOnly>
        <section
          className="hu-section hu-surface"
          data-view-mode="analysis"
        >
          <UniverseSectionHeading
            subtitle="La baisse, le nombre d’occurrences et le risque corrigé restent visibles avec le résultat."
            title="Lire la solidité, pas seulement le rang"
          />
          {page.items.length ? (
            <EvidenceComparisonTable entries={page.items} />
          ) : (
            <HonestEmptyState title="Comparaison indisponible">
              Aucun signal chargé ne permet de produire un tableau comparatif
              pour cette portée.
            </HonestEmptyState>
          )}
          <div className="hu-explainer-grid">
            <MetricExplainer
              expert="Nombre d’observations strictement éligibles après réconciliation."
              name="Occurrences historiques"
              simple="Le nombre de matchs réellement utilisés pour calculer le signal."
            />
            <MetricExplainer
              expert="Plus forte baisse depuis un sommet de la bankroll historique simulée."
              name="Baisse maximale"
              simple="La plus forte baisse traversée par le capital simulé."
            />
            <MetricExplainer
              expert="Valeur q recalculée sur les 700 règles de la campagne."
              name="Risque de faux positif après correction"
              simple="Un garde-fou qui empêche de confondre un résultat spectaculaire avec une preuve solide."
            />
          </div>
        </section>
      </AnalysisOnly>

      <section className="hu-section" id="strategies-validees">
        <UniverseSectionHeading title="Stratégies validées" />
        <HonestEmptyState
          icon="∅"
          title="Aucune stratégie n’est encore scientifiquement validée"
        >
          Ce rapport historique interdit explicitement l’étiquette validée.
          Robin distingue les résultats intéressants des preuves suffisamment
          solides pour être considérées comme fiables.
        </HonestEmptyState>
      </section>

      <ExpertOnly>
        <section
          className="hu-section hu-expert-proof"
          data-view-mode="expert"
        >
          <UniverseSectionHeading
            eyebrow="Vue Expert"
            title="Portée contractuelle brute"
          />
          <dl className="hu-technical-grid">
            <div>
              <dt>Contrat source</dt>
              <dd>
                <code>
                  hypothesis-global-rankings →{" "}
                  {page.provenance.sourceContracts[0]}
                </code>
              </dd>
            </div>
            <div>
              <dt>Portée source</dt>
              <dd>
                <code>{page.sourceScope}</code>
              </dd>
            </div>
            <div>
              <dt>Tri source</dt>
              <dd>
                <code>{page.sourceRanking}</code>
              </dd>
            </div>
            <div>
              <dt>Révision historique</dt>
              <dd>
                <code>{summary.historicalDataRevision}</code>
              </dd>
            </div>
            <div>
              <dt>Hash du jeu de données</dt>
              <dd>
                <code>{summary.datasetHash}</code>
              </dd>
            </div>
            <div>
              <dt>Hash de rejouabilité</dt>
              <dd>
                <code>{summary.replayHash}</code>
              </dd>
            </div>
          </dl>
        </section>
      </ExpertOnly>
    </div>
  );
}
