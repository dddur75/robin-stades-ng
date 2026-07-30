import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  getHistoricalEvidenceRankingPage,
  getHistoricalEvidenceReportSummary,
  getHistoricalHypothesisEvidence,
  HISTORICAL_EVIDENCE_ITEM_LIMIT,
} from "../app/lib/hypothesis-evidence.server";
import {
  formatEvidenceNumber,
  formatEvidencePercent,
  formatEvidenceUnits,
} from "../app/lib/hypothesis-evidence-format";
import { parseRankingListQuery } from "../app/lib/query-params";

test("l’adaptateur serveur ne livre jamais plus que le top 10 borné", () => {
  const page = getHistoricalEvidenceRankingPage(
    parseRankingListQuery(new URLSearchParams()),
  );

  assert.equal(HISTORICAL_EVIDENCE_ITEM_LIMIT, 10);
  assert.equal(page.schemaVersion, "ranking-page-v1.2");
  assert.equal(page.items.length, 10);
  assert.ok(page.items.length <= page.boundedItemLimit);
  assert.equal(page.pagination.totalItems, page.items.length);
  assert.equal(page.sourceRanking, "by_roi");
  assert.equal(page.sort, "roi-desc");
  assert.ok(
    page.items.every(
      (item) =>
        item.scientificStatus ===
        "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
    ),
  );
  assert.ok(
    page.items.every(
      (item) =>
        item.evidence.phase === "historical" &&
        item.evidence.stability === null,
    ),
  );
});

test("les cinq tris reprennent l’ordre source et le hash départage les égalités", () => {
  const cases = [
    ["roi-desc", "roi", "desc"],
    ["profit-desc", "profitUnits", "desc"],
    ["support-desc", "occurrences", "desc"],
    ["hit-rate-desc", "hitRate", "desc"],
    ["drawdown-asc", "maximumDrawdownUnits", "asc"],
  ] as const;

  for (const [sort, metric, direction] of cases) {
    const page = getHistoricalEvidenceRankingPage(
      parseRankingListQuery(new URLSearchParams(`tri=${sort}`)),
    );
    for (let index = 1; index < page.items.length; index += 1) {
      const previous = page.items[index - 1]!;
      const current = page.items[index]!;
      const previousValue = previous.metrics[metric];
      const currentValue = current.metrics[metric];
      if (previousValue === currentValue) {
        assert.ok(previous.ruleHash.localeCompare(current.ruleHash, "en") < 0);
      } else if (direction === "asc") {
        assert.ok(previousValue < currentValue);
      } else {
        assert.ok(previousValue > currentValue);
      }
    }
  }
});

test("une catégorie ou un tri sans classement source retombe sur le contrat historique canonique", () => {
  const query = parseRankingListQuery(
    new URLSearchParams(
      "categorie=validated&tri=result-desc&marche=1X2_AWAY",
    ),
  );
  const page = getHistoricalEvidenceRankingPage(query);

  assert.equal(query.category, "historical_raw");
  assert.equal(query.sort, "roi-desc");
  assert.equal(page.category, "historical_raw");
  assert.equal(page.sort, "roi-desc");
  assert.equal(page.sourceRanking, "by_roi");
  assert.equal(page.activeFilters.market, "1X2_AWAY");
});

test("les filtres compétition, famille, marché, origine et temporalité restent bornés", () => {
  const page = getHistoricalEvidenceRankingPage(
    parseRankingListQuery(
      new URLSearchParams(
        "competition=Liga&famille=market&marche=1X2_AWAY&origine=discovery_exposed&heure-limite=source_price_class_only&tri=profit-desc",
      ),
    ),
  );

  assert.equal(page.scope.kind, "competition");
  assert.equal(page.sourceScope, "by_competition.La Liga");
  assert.ok(page.items.length <= 10);
  assert.ok(
    page.items.every(
      (item) =>
        item.competition === "La Liga" &&
        item.family === "MARKET" &&
        item.market === "1X2_AWAY" &&
        item.origin === "DISCOVERY_EXPOSED" &&
        item.cutoff === null,
    ),
  );
  assert.equal(page.complete, false);
  assert.equal(page.selectionIsCompleteForRequestedTop, false);
});

test("une fiche unique expose les métriques B sans fabriquer de prospectif", () => {
  const evidence = getHistoricalHypothesisEvidence("J10-M001");
  assert.ok(evidence);
  assert.equal(evidence.hypothesisId, "J10-M001");
  assert.equal(evidence.metrics.occurrences, 261);
  assert.equal(evidence.metrics.profitUnits, 43.43);
  assert.equal(evidence.metrics.correctedFalsePositiveRisk, 1);
  assert.equal(evidence.conditions.length, 3);
  assert.deepEqual(evidence.conditions[1], {
    availableAt: "HISTORICAL_PRICE_CATEGORY",
    feature: "market_margin_1x2",
    operator: "LE",
    source: "FOOTBALL_DATA",
    value: 0.06,
  });
  assert.equal(evidence.statisticalCoverage.statisticalGroups, 225);
  assert.equal(evidence.statisticalCoverage.distinctSeasons, 6);
  assert.equal(evidence.statisticalCoverage.distinctTeams, 28);
  assert.equal(evidence.statisticalCoverage.totalStakedUnits, 261);
  assert.equal(evidence.statisticalCoverage.grossReturnsUnits, 304.43);
  assert.equal(evidence.availability.prospective, false);
  assert.equal(evidence.temporalEvidence.pointInTimeClaim, false);
  assert.equal(
    evidence.scientificStatus,
    "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
  );
  assert.match(evidence.provenance.ruleHash, /^[0-9a-f]{64}$/u);
  assert.equal(Object.isFrozen(evidence), true);
  assert.equal(getHistoricalHypothesisEvidence("HYPOTHESE-INCONNUE"), null);
});

test("le résumé réconcilié reste dynamique et sans doublon", () => {
  const summary = getHistoricalEvidenceReportSummary();
  assert.equal(summary.reconciled, true);
  assert.equal(summary.rules, 700);
  assert.equal(summary.fixtures, 10_732);
  assert.equal(summary.memberships, 681_466);
  assert.equal(summary.duplicateMemberships, 0);
  assert.equal(summary.validatedLabelForbidden, true);
  assert.match(summary.datasetHash, /^[0-9a-f]{64}$/u);
  assert.match(summary.historicalDataRevision, /^[0-9a-f]{40}$/u);
});

test("les preuves conservent les centièmes et le signe public", () => {
  assert.equal(formatEvidencePercent(0.166398, true), "+16,64 %");
  assert.equal(formatEvidenceUnits(43.43, true), "+43,43 u");
  assert.equal(formatEvidenceUnits(-2.5, true), "-2,50 u");
  assert.equal(formatEvidenceNumber(2.250421), "2,25");
});

test("aucun composant client n’importe le rapport complet", async () => {
  const source = await readFile(
    new URL(
      "../app/lib/hypothesis-evidence.server.ts",
      import.meta.url,
    ),
    "utf8",
  );
  assert.match(source, /top-10\.json/u);

  const clientCandidates = [
    "../app/components/hypotheses/historical-evidence-ranking-controls.tsx",
    "../app/components/hypotheses/hypothesis-detail-page.tsx",
  ];
  for (const candidate of clientCandidates) {
    const clientSource = await readFile(new URL(candidate, import.meta.url), "utf8");
    assert.doesNotMatch(
      clientSource,
      /reports\/hypothesis-evidence|top-10\.json|artifact-hashes\.json/u,
    );
  }
});
