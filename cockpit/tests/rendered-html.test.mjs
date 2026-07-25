import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
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
  assert.match(html, /DOUBLE ÉCRITURE/i);
  assert.match(html, /19[\s ]992/);
  assert.doesNotMatch(html, /LIVE_SHADOW_VALIDATED/);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("ships a provenance-aware, disposable static snapshot", async () => {
  const [page, layout, data, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

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
  assert.match(data, /"productionStatus": "PRODUCTION_LOCKED"/);
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
