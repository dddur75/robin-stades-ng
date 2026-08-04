import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import rawQuality from "../app/hypothesis-quality-data.json";
import { buildP0CoverageDeskModel } from "../app/lib/p0-coverage-desk";
import rawProjection from "../private-coverage/p0-denominator-status-v1.json";

const calendarPropertyIds = rawQuality.semanticRoles.items
  .filter((item) => item.family === "CALENDAR_FATIGUE")
  .map((item) => item.property_id.replace("football:calendar_fatigue:", ""));

function cloneProjection(): typeof rawProjection {
  return structuredClone(rawProjection);
}

test("le modèle P0 compact valide 5 × 6 × 16 sans sérialiser les cellules", () => {
  const model = buildP0CoverageDeskModel(rawProjection, calendarPropertyIds);
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
  const projection = cloneProjection();
  projection.weighted_aggregates.scope_completion.value = 0;
  assert.throws(
    () => buildP0CoverageDeskModel(projection, calendarPropertyIds),
    /P0_COVERAGE_UNKNOWN_RATE_MUST_STAY_NULL/,
  );

  const forbidden = cloneProjection();
  forbidden.cells[0].rates.coverage_rate = forbidden.cells[0].rates.scope_completion;
  assert.throws(
    () => buildP0CoverageDeskModel(forbidden, calendarPropertyIds),
    /P0_COVERAGE_RATE_SET_INVALID/,
  );
});

test("les mutations de grille, confidentialité et navigation échouent fermées", () => {
  const missing = cloneProjection();
  missing.cells.pop();
  assert.throws(
    () => buildP0CoverageDeskModel(missing, calendarPropertyIds),
    /P0_COVERAGE_CELL_COUNT_INVALID/,
  );

  const endpoint = cloneProjection();
  endpoint.cells[0].source_endpoint = "api-football:/fixtures";
  assert.throws(
    () => buildP0CoverageDeskModel(endpoint, calendarPropertyIds),
    /P0_COVERAGE_CELL_PRIVACY_INVALID/,
  );

  const count = cloneProjection();
  count.cells[0].expected_count = 0;
  assert.throws(
    () => buildP0CoverageDeskModel(count, calendarPropertyIds),
    /P0_COVERAGE_UNPROVEN_COUNT_MUST_STAY_NULL/,
  );

  const navigation = cloneProjection();
  navigation.navigation_gates.strategy = "AVAILABLE";
  assert.throws(
    () => buildP0CoverageDeskModel(navigation, calendarPropertyIds),
    /P0_COVERAGE_NAVIGATION_INVALID/,
  );
});

test("les 17 propriétés Calendar restent identiques au catalogue autoritatif", () => {
  assert.equal(calendarPropertyIds.length, 17);
  assert.ok(calendarPropertyIds.includes("matches_5d"));
  assert.ok(calendarPropertyIds.includes("matches_10d"));
  assert.ok(!calendarPropertyIds.includes("away_matches_14d"));
  assert.doesNotThrow(() =>
    buildP0CoverageDeskModel(rawProjection, calendarPropertyIds),
  );
  assert.throws(
    () =>
      buildP0CoverageDeskModel(rawProjection, [
        ...calendarPropertyIds.slice(0, -1),
        "invented_property",
      ]),
    /P0_COVERAGE_CALENDAR_CATALOG_MISMATCH/,
  );
});

test("la projection lourde reste derrière une frontière serveur", async () => {
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
  assert.match(serverSource, /private-coverage\/p0-denominator-status-v1\.json/);
  assert.doesNotMatch(componentSource, /private-coverage|p0-denominator-status-v1/);
  assert.match(pageSource, /p0-coverage-desk\.server/);
  assert.match(componentSource, /aria-disabled="true"/);
});
