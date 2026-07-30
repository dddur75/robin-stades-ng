import assert from "node:assert/strict";
import test from "node:test";

import {
  nodeMatchesUnderstoodFilters,
  parseFrenchHypothesisQuery,
} from "../app/lib/hypothesis-filter";
import type { HypothesisTreeNode } from "../app/lib/hypothesis-universe";

function node(
  partial: Partial<HypothesisTreeNode> = {},
): HypothesisTreeNode {
  return {
    children_count: 0,
    data_gates: [],
    display_rule_fr: "Branche de test",
    family: "WEATHER",
    historical_metrics: null,
    materialization_disposition: "EXECUTED",
    node_id: "test-node",
    parent_id: null,
    parent_ids: [],
    payload_hash: "test",
    prospective_metrics: null,
    rankings: null,
    status: "NOT_TESTED",
    subfamily: "WIND",
    support: 250,
    tags: [],
    technical_rule: {},
    ...partial,
  };
}

test("OU forme une vraie alternative et non une conjonction", () => {
  const filters = parseFrenchHypothesisQuery("Météo OU fatigue");
  assert.deepEqual(
    filters
      .filter((filter) => filter.field === "family")
      .map((filter) => filter.operator),
    ["ET", "OU"],
  );
  assert.equal(
    nodeMatchesUnderstoodFilters(node({ family: "WEATHER" }), filters),
    true,
  );
  assert.equal(
    nodeMatchesUnderstoodFilters(
      node({ family: "CALENDAR_FATIGUE" }),
      filters,
    ),
    true,
  );
  assert.equal(
    nodeMatchesUnderstoodFilters(node({ family: "MARKET" }), filters),
    false,
  );
});

test("ET et SAUF se composent sans contaminer la clause suivante", () => {
  const filters = parseFrenchHypothesisQuery(
    "Liga ET plus de 200 matchs SAUF branches bloquées",
  );
  const eligible = node({ support: 250, tags: ["La Liga"] });
  const blocked = node({
    materialization_disposition: "DATA_GATE_BLOCKED",
    support: 250,
    tags: ["La Liga"],
  });
  assert.equal(nodeMatchesUnderstoodFilters(eligible, filters), true);
  assert.equal(nodeMatchesUnderstoodFilters(blocked, filters), false);
  assert.equal(
    nodeMatchesUnderstoodFilters(
      node({ support: 100, tags: ["La Liga"] }),
      filters,
    ),
    false,
  );
});

test("les concepts d’une même clause sont combinés explicitement", () => {
  const filters = parseFrenchHypothesisQuery("Météo et vent fort");
  assert.ok(filters.every((filter) => filter.operator === "ET"));
  assert.ok(filters.every((filter) => filter.segment >= 0));
  assert.equal(
    nodeMatchesUnderstoodFilters(
      node({ display_rule_fr: "Vent fort avant le match" }),
      filters,
    ),
    true,
  );
});
