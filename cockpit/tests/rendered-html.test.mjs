import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Cockpit Live V2 shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Robin des Stades — Cockpit Live V2<\/title>/i);
  assert.match(html, /Command Center/);
  assert.match(html, /PRODUCTION_LOCKED/);
  assert.match(html, /LIVE SOURCE/);
  assert.match(html, /SHADOW COLLECTION HARDENED/);
  assert.match(html, /Snapshots réels/);
  assert.match(html, /Coverage Explorer/);
  assert.match(html, /Registre PostgreSQL/);
  assert.match(html, /101/);
  assert.match(html, /PostgreSQL/);
  assert.match(html, /Robin Live V1/);
  assert.match(html, /Matchup Lab/);
  assert.match(html, /Preuve publique shadow/);
  assert.match(html, /Bankroll shadow/);
  assert.match(html, /NO BET/);
  assert.match(html, /NO LIVE SHADOW DATA/);
  assert.match(html, /SOCIAL_PUBLISHING_ENABLED=false/);
  assert.match(html, /DOUBLE ÉCRITURE/i);
  assert.match(html, /19[\s ]992/);
  assert.doesNotMatch(html, /LIVE_SHADOW_VALIDATED/);
  assert.doesNotMatch(html, /garantie de gain|gain garanti|100 % gagnant/i);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("server-renders the public Robin Live V1 route", async () => {
  const response = await render("/robin-live");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Robin Live V1/);
  assert.match(html, /WHAT_WAS_TESTED/);
  assert.match(html, /WHAT_WAS_NOT_TESTED/);
  assert.match(html, /Walk-forward brut avant FDR/);
  assert.match(html, /Trois meilleurs résultats bruts/);
  assert.match(
    html,
    /EXPLORATORY REJECTED AFTER MULTIPLE TESTING/,
  );
  assert.match(html, /N\/A — aucun pari réglé/);
  assert.match(html, /PRODUCTION_LOCKED/);
  assert.match(html, /SOCIAL_PUBLISHING_ENABLED=false/);
  assert.match(html, /Matchup Lab/);
  assert.match(html, /aucune promotion implicite/i);
  assert.match(html, /aucune donnée démo n.*est présentée comme live/i);
  assert.match(html, /TEAM_GATE PARTIAL/);
  assert.match(html, /0\.001702/);
  assert.doesNotMatch(html, /LIVE_SHADOW_VALIDATED/);
});

test("ships a provenance-aware, disposable static snapshot", async () => {
  const [page, layout, data, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  const research = JSON.parse(data).patternResearch;
  const matchup = JSON.parse(data).matchupLab;
  const deep = JSON.parse(data).deepData;
  assert.deepEqual(
    {
      generated: research.laboratory.hypothesesGenerated,
      rawPositive: research.laboratory.rawPositive,
      walkForwardRaw: research.laboratory.walkForwardRawBeforeFdr,
      fdr: research.laboratory.fdrSurvivors,
      candidates: research.strategies.shadowCandidates,
      supportRejected: research.strategies.supportRejected,
      promotionRejected: research.strategies.promotionRejected,
    },
    {
      generated: 700,
      rawPositive: 118,
      walkForwardRaw: 24,
      fdr: 0,
      candidates: 0,
      supportRejected: 167,
      promotionRejected: 700,
    },
  );
  assert.equal(research.subVerdict, "NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE");
  assert.equal(research.results.roi, null);
  assert.equal(research.bankroll.currentUnits, 1000);
  assert.equal(research.ledger.status, "LEDGER_VERIFIED");
  assert.equal(research.productionStatus, "PRODUCTION_LOCKED");
  assert.equal(research.realBets, false);
  assert.equal(research.noBetDefault, true);
  assert.equal(research.socialPublishingEnabled, false);
  assert.equal(research.demoModeEnabled, false);
  assert.equal(matchup.version, "MATCHUP_LAB_V1");
  assert.equal(matchup.locks.productionStatus, "PRODUCTION_LOCKED");
  assert.equal(matchup.locks.realBets, false);
  assert.equal(matchup.locks.noBetDefault, true);
  assert.equal(matchup.locks.socialPublishingEnabled, false);
  assert.equal(matchup.locks.demoModeEnabled, false);
  assert.equal(matchup.costs.providerCalls, 0);
  assert.equal(matchup.costs.oddsApiCredits, 0);
  assert.equal(matchup.watchlist.notABet, true);
  assert.equal(matchup.promotion.promoted, false);
  assert.ok(matchup.promotion.criteria.length > 0);
  assert.ok(
    matchup.promotion.criteria.every(
      (criterion) =>
        typeof criterion.name === "string" &&
        typeof criterion.passed === "boolean",
    ),
  );
  assert.deepEqual(
    matchup.promotion.criteria.filter((criterion) =>
      ["data_gate_ready", "no_leakage"].includes(criterion.name),
    ),
    [
      { name: "data_gate_ready", passed: false },
      { name: "no_leakage", passed: false },
    ],
  );
  assert.equal(matchup.verdict, "JALON_11_BLOCKED_BY_DATA_GATES");
  assert.equal(matchup.dataset.rows, 10732);
  assert.equal(matchup.dataset.pairing.leftAttrition, 0);
  assert.equal(matchup.dataset.pairing.rightAttrition, 2235);
  assert.equal(matchup.coverage.competitions.length, 5);
  assert.equal(matchup.experiments.campaigns.length, 7);
  assert.equal(matchup.experiments.ownerHypotheses.length, 8);
  assert.ok(
    matchup.experiments.ownerHypotheses.every(
      (hypothesis) =>
        hypothesis.frozenBeforeResults === true &&
        hypothesis.minimumSupport >= 80 &&
        hypothesis.cutoff !== "UNSPECIFIED" &&
        /^[0-9a-f]{64}$/.test(hypothesis.preregistrationHash),
    ),
  );
  assert.equal(matchup.coverage.gates.length, 9);
  assert.equal(matchup.results.campaign, "11A");
  assert.equal(
    matchup.results.status,
    "DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC",
  );
  assert.equal(
    matchup.coverage.gates.find((gate) => gate.name === "TEAM_GATE").status,
    "PARTIAL",
  );
  assert.equal(matchup.results.models.length, 8);
  assert.equal(
    matchup.results.models.filter((model) => model.id.startsWith("B0_")).length,
    2,
  );
  assert.equal(matchup.negativeControls.length, 12);
  assert.deepEqual(matchup.negativeControlSummary, {
    total: 12,
    executedOrGuard: 6,
    dataGated: 6,
  });
  assert.equal(
    matchup.results.pairedComparator.deltaLogLoss,
    0.00170221115952107,
  );
  assert.equal(matchup.results.folds.length, 4);
  assert.equal(
    matchup.results.folds.filter(
      (fold) => fold.outcome === "LOST_TO_RECALIBRATED_MARKET",
    ).length,
    3,
  );
  assert.equal(matchup.results.crossLeague.rotationCount, 5);
  assert.equal(matchup.results.crossLeague.survivors, 0);
  assert.equal(matchup.watchlist.count, 0);
  assert.equal(matchup.decision.candidateCount, 0);
  assert.equal(matchup.decision.decisions, 0);
  assert.equal(matchup.decision.stakeUnits, 0);
  assert.equal(matchup.replay.hashComparisons.length, 4);
  assert.ok(matchup.replay.hashComparisons.every((item) => item.matched));
  assert.equal(matchup.replay.providerCalls, 0);
  assert.equal(matchup.replay.oddsApiCredits, 0);
  assert.equal(
    matchup.results.resultHash,
    "437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355",
  );
  assert.equal(matchup.replay.resultHash, matchup.results.resultHash);
  assert.equal(
    matchup.ledger.headHash,
    "7f52801f6a4fee8786df0fd71c1f5af3d26dbed31168ebe1e422ba387ccd3ddf",
  );
  assert.equal(
    matchup.provenance.sourceCommit,
    "803091cb506e17a07850f56ef78b7b9df55575dd",
  );
  assert.equal(
    matchup.provenance.mainCommit,
    "31ec41632b72cd93676f5b1d8592e1bba429e937",
  );
  assert.equal(
    matchup.provenance.codeRevision,
    "31ec41632b72cd93676f5b1d8592e1bba429e937",
  );
  assert.equal(matchup.costs.historicalBytes, 985499173);
  assert.equal(matchup.costs.databaseBytes, 47366144);
  assert.equal(matchup.costs.r2ExpectedBytes, 974079201);
  assert.equal(matchup.costs.r2LagObjects, 0);
  assert.equal(matchup.ledger.status, "HASH_CHAIN_VERIFIED");
  assert.equal(matchup.ledger.events, 27);
  assert.ok(deep.datasets.length >= 6);
  assert.ok(deep.models.length >= 9);
  assert.ok(deep.backtests.length >= 15);
  assert.ok(deep.strategies.length >= 17);
  assert.equal(research.laboratory.topExploratoryResults.length, 3);
  for (const result of research.laboratory.topExploratoryResults) {
    assert.equal(
      result.publicStatus,
      "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
    );
    assert.equal(result.qValue, 1);
  }

  assert.match(page, /Odds Explorer/);
  assert.match(page, /Coverage Explorer/);
  assert.match(page, /Shadow Performance/);
  assert.match(page, /Pipeline & Qualité/);
  assert.match(page, /Coûts & Quotas/);
  assert.match(page, /Data Explorer/);
  assert.match(page, /Deep Data Command Center/);
  assert.match(page, /Backfill Monitor/);
  assert.match(page, /Player Explorer/);
  assert.match(page, /Dataset Readiness/);
  assert.match(page, /Lineup Explorer/);
  assert.match(page, /Feature Lab/);
  assert.match(page, /Model Lab/);
  assert.match(page, /Model Arena/);
  assert.match(page, /Attrition équipe/);
  assert.match(page, /pairing\.rightAttrition/);
  assert.match(page, /Matchup Lab/);
  assert.match(page, /Score Comparisons/);
  assert.match(page, /Comparison Table/);
  assert.match(page, /Paired Comparator/);
  assert.match(page, /Where the Model Lost/);
  assert.match(page, /Robustness/);
  assert.match(page, /League Decomposition/);
  assert.match(page, /Data Gates/);
  assert.match(page, /Research vs Production/);
  assert.match(page, /Prospective Shadow/);
  assert.match(page, /Costs \/ Usage/);
  assert.match(page, /Watchlist vide — aucun candidat robuste/);
  assert.match(page, /Ledger V2 et provenance/);
  assert.match(page, /Budget nul, stockage sous contrôle/);
  assert.doesNotMatch(page, /deux modèles/i);
  assert.match(page, /External Validation/);
  assert.match(page, /External Readiness/);
  assert.match(page, /League Transfer Matrix/);
  assert.match(page, /Leave-One-League-Out/);
  assert.match(page, /Player Generalization/);
  assert.match(page, /Strategy External Validation/);
  assert.match(page, /Preseason Package/);
  assert.match(page, /NO_BET_DEFAULT/);
  assert.match(page, /REAL_BETS/);
  assert.match(page, /Comparaison appariée/);
  assert.match(page, /CI 90/);
  assert.match(page, /CI 95/);
  assert.match(page, /Model Leaderboard/);
  assert.match(page, /Head-to-Head/);
  assert.match(page, /Calibration Lab/);
  assert.match(page, /Feature Ablation/);
  assert.match(page, /Score Models/);
  assert.match(page, /OOS Governance/);
  assert.match(page, /Strategy Lab/);
  assert.match(page, /Backtest Explorer/);
  assert.match(page, /Historical Data Quality/);
  assert.match(page, /Robin Live V1/);
  assert.match(page, /Décisions shadow et NO BET/);
  assert.match(page, /Hypothèses, FDR et contrôles négatifs/);
  assert.match(data, /Les performances passées ne garantissent aucun résultat futur/);
  assert.match(page, /SOCIAL_PUBLISHING_ENABLED=false/);
  assert.match(page, /LIVE_PIPELINE_VERIFIED/);
  assert.match(page, /EN ATTENTE DE DONNÉES PROSPECTIVES/);
  assert.match(page, /AUCUNE CONCLUSION STATISTIQUE|statistical_message/);
  assert.match(layout, /lang="fr"/);
  assert.match(layout, /images: \["\/og\.png"\]/);
  assert.match(data, /"productionStatus": "PRODUCTION_LOCKED"/);
  assert.match(data, /"shadowStatus": "SHADOW_COLLECTION_HARDENED"/);
  assert.match(data, /"origin": "LIVE SOURCE"/);
  assert.match(data, /"origin": "LEGACY SOURCE"/);
  assert.match(data, /"stateArtifact": "shadow-state-30095263615"/);
  assert.match(data, /"snapshots": 2/);
  assert.match(data, /"durableRecords": 101/);
  assert.match(data, /"demoModeEnabled": false/);
  assert.match(data, /"bridge_status": "ACTIVE_AND_VERIFIED"/);
  assert.match(data, /"target_status": "CONNECTED_AND_PERSISTED"/);
  assert.match(data, /"bridge_lag_records": 0/);
  assert.match(data, /"capacity_used_pct": 2\.39/);
  assert.match(data, /"deepData":/);
  assert.match(data, /"patternResearch":/);
  assert.match(data, /"matchupLab":/);
  assert.match(data, /"version": "MATCHUP_LAB_V1"/);
  assert.match(data, /"version": "ROBIN_LIVE_V1"/);
  assert.match(data, /"dataStatus": "NO_LIVE_SHADOW_DATA"/);
  assert.match(data, /"initialUnits": 1000(?:\.0)?/);
  assert.match(data, /"currentUnits": 1000(?:\.0)?/);
  assert.match(data, /"fdrMethod": "Benjamini-Hochberg"/);
  assert.match(data, /"socialPublishingEnabled": false/);
  assert.match(data, /"realBets": false/);
  assert.match(data, /"demoModeEnabled": false/);
  assert.match(data, /"productionStatus": "PRODUCTION_LOCKED"/);
  assert.doesNotMatch(page, /DATABASE_URL|API_FOOTBALL_KEY|ODDS_API_KEY|R2_SECRET_ACCESS_KEY/);
  assert.match(data, /"HISTORICAL POINT-IN-TIME"/);
  assert.match(
    data,
    /"(?:OOS_BACKTEST_V1_READY|API_OOS_BACKTEST_READY)"/,
  );
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await access(new URL("../public/og.png", import.meta.url));
  try {
    assert.deepEqual(
      await readdir(new URL("../app/_sites-preview", import.meta.url)),
      [],
    );
  } catch (error) {
    assert.equal(error.code, "ENOENT");
  }
  await assert.rejects(access(new URL("package-lock.json", root)));
});

test("public ledger workflow publishes the audited Robin Live bundle", async () => {
  const workflow = await readFile(
    new URL("../../.github/workflows/public-ledger-build.yml", import.meta.url),
    "utf8",
  );
  assert.match(workflow, /group: shadow-state/);
  assert.match(workflow, /PATTERN_LEDGER_SUMMARY:/);
  assert.match(workflow, /artifacts\/public-ledger\/ledger-summary\.json/);
  assert.match(workflow, /test -f dist\/server\/index\.js/);
  assert.match(workflow, /cockpit\/dist/);
  assert.match(workflow, /if-no-files-found: error/);
  assert.doesNotMatch(workflow, /cockpit\/out/);
});
