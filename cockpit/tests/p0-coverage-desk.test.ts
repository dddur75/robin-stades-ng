import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import rawQuality from "../app/hypothesis-quality-data.json";
import { buildP0CoverageDeskModel } from "../app/lib/p0-coverage-desk";
import denominatorContract from "../../configs/data/historical-coverage-denominator-contract-v1.json";
import grainCatalog from "../../configs/data/football-grain-catalog-v1.json";
import closureSummary from "../../reports/coverage/denominator-closure-summary-v1.json";
import propertyReadiness from "../../reports/coverage/p0-property-readiness-v1.json";
import readinessGates from "../../reports/coverage/p0-readiness-gates-v1.json";

const calendarPropertyIds = rawQuality.semanticRoles.items
  .filter((item) => item.family === "CALENDAR_FATIGUE")
  .map((item) => item.property_id.replace("football:calendar_fatigue:", ""));

const rawSources = {
  contract: denominatorContract,
  grainCatalog,
  summary: closureSummary,
  propertyReadiness,
  readinessGates,
};

function cloneSources(): typeof rawSources {
  return structuredClone(rawSources);
}

test("le modèle P0 compact valide 5 × 6 × 16 sans sérialiser les cellules", () => {
  const model = buildP0CoverageDeskModel(rawSources, calendarPropertyIds);
  assert.equal(model.totalCells, 480);
  assert.equal(model.closedCells, 0);
  assert.equal(model.openCells, 480);
  assert.equal(model.competitionCount, 5);
  assert.equal(model.seasonCount, 6);
  assert.equal(model.familyCount, 16);
  assert.equal(model.calendarReady, 0);
  assert.equal(model.calendarTotal, 17);
  assert.equal(model.functionalGatesReady, 0);
  assert.equal(model.functionalGatesTotal, 8);
  assert.equal(model.families.length, 16);
  assert.ok(model.families.every((family) => family.expectedCells === 30));
  assert.ok(model.rates.every((rate) => rate.displayValue === "Non mesuré"));
  assert.ok(Object.isFrozen(model));
  assert.ok(Object.isFrozen(model.families));
  assert.doesNotMatch(JSON.stringify(model), /cell_id|source_endpoint|payload_hash/);
  assert.ok(JSON.stringify(model).length < 50_000);
});

test("UNKNOWN reste distinct de zéro et aucun taux ambigu n'est accepté", () => {
  const sources = cloneSources();
  sources.summary.weighted_aggregates.scope_completion.value = 0;
  assert.throws(
    () => buildP0CoverageDeskModel(sources, calendarPropertyIds),
    /P0_COVERAGE_UNKNOWN_RATE_MUST_STAY_NULL/,
  );

  const forbidden = cloneSources();
  Object.assign(forbidden.summary.weighted_aggregates, {
    coverage_rate: forbidden.summary.weighted_aggregates.scope_completion,
  });
  assert.throws(
    () => buildP0CoverageDeskModel(forbidden, calendarPropertyIds),
    /P0_COVERAGE_RATE_SET_INVALID/,
  );
});

test("les incohérences de sources compactes échouent fermées", () => {
  const missing = cloneSources();
  missing.contract.grid.families.pop();
  assert.throws(
    () => buildP0CoverageDeskModel(missing, calendarPropertyIds),
    /P0_COVERAGE_DIMENSIONS_INVALID/,
  );

  const externalEffect = cloneSources();
  externalEffect.summary.provider_calls = 1;
  assert.throws(
    () => buildP0CoverageDeskModel(externalEffect, calendarPropertyIds),
    /P0_COVERAGE_EXTERNAL_EFFECT_INVALID/,
  );

  const familyMismatch = cloneSources();
  familyMismatch.propertyReadiness.family_readiness[0].family = "invented_family";
  assert.throws(
    () => buildP0CoverageDeskModel(familyMismatch, calendarPropertyIds),
    /P0_COVERAGE_FAMILY_BINDINGS_INVALID/,
  );

  const unventilatedClosure = cloneSources();
  unventilatedClosure.summary.closed_cells = 1;
  unventilatedClosure.summary.open_cells = 479;
  assert.throws(
    () => buildP0CoverageDeskModel(unventilatedClosure, calendarPropertyIds),
    /P0_COVERAGE_FAMILY_BREAKDOWN_REQUIRED/,
  );

  const coverageGate = cloneSources();
  coverageGate.readinessGates.coverage_gate.current_closed_cells = 480;
  coverageGate.readinessGates.coverage_gate.status = "READY";
  assert.throws(
    () => buildP0CoverageDeskModel(coverageGate, calendarPropertyIds),
    /P0_COVERAGE_COVERAGE_GATE_INVALID/,
  );

  const openedGate = cloneSources();
  openedGate.readinessGates.gates[0].status = "READY";
  assert.throws(
    () => buildP0CoverageDeskModel(openedGate, calendarPropertyIds),
    /P0_COVERAGE_GATE_STATUS_INVALID/,
  );

  const unlocked = cloneSources();
  unlocked.summary.scale_authorized = true;
  unlocked.summary.promotion = true;
  unlocked.propertyReadiness.opens_hypergraph = true;
  assert.throws(
    () => buildP0CoverageDeskModel(unlocked, calendarPropertyIds),
    /P0_COVERAGE_LOCKS_INVALID/,
  );

  const calendarMismatch = cloneSources();
  calendarMismatch.summary.calendar_fatigue.ready_properties = 17;
  calendarMismatch.summary.calendar_fatigue.opens_hypergraph = true;
  assert.throws(
    () => buildP0CoverageDeskModel(calendarMismatch, calendarPropertyIds),
    /P0_COVERAGE_CALENDAR_STATE_INVALID/,
  );
});

test("les 17 propriétés Calendar restent identiques au catalogue autoritatif", () => {
  assert.equal(calendarPropertyIds.length, 17);
  assert.ok(calendarPropertyIds.includes("matches_5d"));
  assert.ok(calendarPropertyIds.includes("matches_10d"));
  assert.ok(!calendarPropertyIds.includes("away_matches_14d"));
  assert.doesNotThrow(() =>
    buildP0CoverageDeskModel(rawSources, calendarPropertyIds),
  );
  assert.throws(
    () =>
      buildP0CoverageDeskModel(rawSources, [
        ...calendarPropertyIds.slice(0, -1),
        "invented_property",
      ]),
    /P0_COVERAGE_CALENDAR_CATALOG_MISMATCH/,
  );
});

test("les sources compactes restent derrière une frontière serveur", async () => {
  const [serverSource, componentSource, pageSource] = await Promise.all([
    readFile(new URL("../app/lib/p0-coverage-desk.server.ts", import.meta.url), "utf8"),
    readFile(
      new URL("../app/components/expert/p0-coverage-desk.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/expert/qualite-donnees/page.tsx", import.meta.url),
      "utf8",
    ),
  ]);
  assert.match(serverSource, /historical-coverage-denominator-contract-v1\.json/);
  assert.match(serverSource, /denominator-closure-summary-v1\.json/);
  assert.doesNotMatch(serverSource, /private-coverage|p0-denominator-status-v1/);
  assert.doesNotMatch(componentSource, /private-coverage|p0-denominator-status-v1/);
  assert.match(pageSource, /p0-coverage-desk\.server/);
  assert.match(componentSource, /aria-disabled="true"/);
});
