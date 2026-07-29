import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const universeUrl = new URL(
  "../app/hypothesis-universe-data.json",
  import.meta.url,
);
const universe = JSON.parse(await readFile(universeUrl, "utf8"));
const contracts = universe.contracts;
const summary = contracts["hypothesis-universe-summary"];
const families = contracts["hypothesis-family-catalog"].items;
const funnel = contracts["hypothesis-status-funnel"];
const tree = contracts["hypothesis-tree-root-index"];
const globalRankings = contracts["hypothesis-global-rankings"];

function values(record) {
  return Object.values(record ?? {});
}

test("le contrat public dérive les chiffres de l’univers sans liste frontend divergente", () => {
  assert.equal(summary.property_families, 28);
  assert.equal(families.length, summary.property_families);
  assert.equal(new Set(families.map((family) => family.family)).size, families.length);
  assert.equal(
    new Set(families.map((family) => family.display_name_fr)).size,
    families.length,
  );

  const propertyCount = families.reduce(
    (total, family) => total + family.property_count,
    0,
  );
  assert.equal(propertyCount, summary.properties);
  assert.equal(propertyCount, 486);
  assert.ok(
    families.some(
      (family) =>
        family.family === "FORMATION_STRUCTURE" &&
        family.display_name_fr === "Formations et structures",
    ),
  );
  assert.ok(
    families.some(
      (family) =>
        family.family === "WEATHER" && family.display_name_fr === "Météo",
    ),
  );

  const generatedRules = values(funnel.counts).reduce(
    (total, count) => total + count,
    0,
  );
  const materializedRules =
    funnel.counts.EXECUTED +
    funnel.counts.DATA_GATE_BLOCKED +
    funnel.counts.PRUNED +
    funnel.counts.LONG_TAIL_WATCHLIST;

  assert.equal(generatedRules, 1_092);
  assert.equal(materializedRules, summary.materialized_candidates);
  assert.equal(materializedRules, tree.node_count);
  assert.equal(funnel.counts.EXECUTED, summary.executed_candidates);
  assert.equal(
    funnel.counts.DATA_GATE_BLOCKED,
    summary.data_gate_blocked_candidates,
  );
  assert.equal(funnel.counts.PRUNED, summary.pruned_candidates);
  assert.equal(funnel.counts.LONG_TAIL_WATCHLIST, summary.long_tail_candidates);
  assert.equal(
    funnel.counts.COMPUTE_DEFERRED,
    summary.compute_deferred_candidates,
  );
  assert.equal(summary.prospectively_frozen_candidates, 3);
});

test("zéro stratégie validée reste cohérent dans chaque classement", () => {
  assert.equal(funnel.validated_strategies, 0);
  assert.deepEqual(globalRankings.strategies_validees, []);

  for (const [competition, ranking] of Object.entries(
    contracts["hypothesis-rankings-by-competition"].competitions,
  )) {
    assert.deepEqual(
      ranking.strategies_validees,
      [],
      `classement compétition ${competition}`,
    );
  }
  for (const [family, ranking] of Object.entries(
    contracts["hypothesis-rankings-by-family"].families,
  )) {
    assert.deepEqual(
      ranking.strategies_validees,
      [],
      `classement famille ${family}`,
    );
  }
});

test("les pages de nœuds, le localisateur et l’index enfants décrivent les mêmes 180 nœuds", async () => {
  const allNodes = [];
  for (const descriptor of universe.generatedNodePages) {
    assert.match(
      descriptor.url,
      /^\/data\/hypotheses\/nodes\/page-\d{3}\.json$/,
    );
    assert.ok(descriptor.records > 0);
    assert.ok(descriptor.records <= tree.page_size);

    const pageUrl = new URL(`../public${descriptor.url}`, import.meta.url);
    const source = await readFile(pageUrl);
    const servedDigest = createHash("sha256").update(source).digest("hex");
    const payload = JSON.parse(source.toString("utf8"));
    const manifestDescriptor = contracts.manifest.detail_pages.find(
      (candidate) => candidate.page === descriptor.page,
    );

    assert.equal(payload.page, descriptor.page);
    assert.equal(payload.items.length, descriptor.records);
    assert.match(descriptor.sha256, /^[a-f0-9]{64}$/);
    assert.equal(descriptor.sha256, servedDigest);
    assert.equal(descriptor.sourceSha256, manifestDescriptor?.sha256);
    assert.equal(descriptor.records, manifestDescriptor?.records);
    for (const node of payload.items) {
      assert.equal(
        universe.derivedTreeIndex.nodeLocator[node.node_id],
        descriptor.page,
        node.node_id,
      );
      allNodes.push(node);
    }
  }

  assert.equal(allNodes.length, tree.node_count);
  assert.equal(new Set(allNodes.map((node) => node.node_id)).size, tree.node_count);
  assert.equal(
    Object.keys(universe.derivedTreeIndex.nodeLocator).length,
    tree.node_count,
  );

  const nodeIds = new Set(allNodes.map((node) => node.node_id));
  const expectedChildren = new Map();
  for (const node of allNodes) {
    for (const parentId of node.parent_ids) {
      assert.ok(nodeIds.has(parentId), `parent absent : ${parentId}`);
      const children = expectedChildren.get(parentId) ?? [];
      children.push(node.node_id);
      expectedChildren.set(parentId, children);
    }
  }

  for (const [parentId, childIds] of Object.entries(
    universe.derivedTreeIndex.childrenByParent,
  )) {
    assert.ok(nodeIds.has(parentId), `index parent absent : ${parentId}`);
    assert.deepEqual(
      [...childIds].sort(),
      [...(expectedChildren.get(parentId) ?? [])].sort(),
      parentId,
    );
  }
  assert.deepEqual(
    Object.keys(universe.derivedTreeIndex.childrenByParent).sort(),
    [...expectedChildren.keys()].sort(),
  );

  for (const root of tree.roots) {
    assert.ok(nodeIds.has(root.node_id), `racine absente : ${root.node_id}`);
    assert.equal(root.parent_id, null);
  }
});

test("les verrous scientifiques et opérationnels sont fermés dans la présentation", () => {
  assert.deepEqual(contracts["security-locks"], {
    DEMO_MODE_ENABLED: false,
    NO_BET_DEFAULT: true,
    P3_P4_PAUSED: true,
    PRODUCTION_LOCKED: true,
    PROMOTION_LOCKED: true,
    REAL_BETS: false,
    SOCIAL_PUBLISHING_ENABLED: false,
    STORAGE_PAUSED: true,
    odds_api_credits: 0,
    paid_weather_calls: 0,
    provider_calls: 0,
  });

  const freeze = contracts["prospective-freeze-provenance-v2"];
  assert.equal(freeze.contracts.length, summary.prospectively_frozen_candidates);
  assert.ok(freeze.contracts.every((contract) => contract.promotion_locked));
  assert.equal(contracts["hypothesis-live-activity"].real_bets, 0);
});
