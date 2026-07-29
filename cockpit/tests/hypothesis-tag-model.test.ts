import assert from "node:assert/strict";
import test from "node:test";

import {
  hypothesisFacets,
  hypothesisTag,
  hypothesisTagCatalog,
  hypothesisTags,
} from "../app/lib/hypothesis-universe";

test("le modèle central expose les champs sémantiques de chaque tag", () => {
  assert.ok(hypothesisTagCatalog.length > hypothesisTags.families.length);
  const tagIds = new Set(hypothesisTagCatalog.map((tag) => tag.tag_id));
  assert.equal(tagIds.size, hypothesisTagCatalog.length);
  for (const tag of hypothesisTagCatalog) {
    assert.ok(tag.tag_id);
    assert.ok(tag.label_fr);
    assert.ok(tag.description_fr);
    assert.ok(tag.icon);
    assert.ok(tag.semantic_role);
    assert.ok("family" in tag);
    assert.ok("parent_tag" in tag);
    if (tag.parent_tag) assert.ok(tagIds.has(tag.parent_tag), tag.tag_id);
  }
  assert.deepEqual(
    new Set(hypothesisTagCatalog.map((tag) => tag.semantic_role)),
    new Set([
      "CUTOFF",
      "FAMILY",
      "MARKET",
      "ORIGIN",
      "PROPERTY",
      "STATUS",
      "SUBFAMILY",
      "SUBJECT",
      "VALUE",
    ]),
  );
});

test("familles, origines, marchés, heures limites et statuts viennent des contrats", () => {
  for (const family of hypothesisTags.families) {
    assert.equal(
      hypothesisTag(`family:${family.id}`)?.label_fr,
      family.label_fr,
    );
  }
  for (const origin of Object.keys(hypothesisTags.origins)) {
    assert.equal(hypothesisTag(`origin:${origin}`)?.semantic_role, "ORIGIN");
  }
  for (const market of hypothesisFacets.markets) {
    assert.equal(hypothesisTag(`market:${market}`)?.semantic_role, "MARKET");
  }
  for (const cutoff of hypothesisFacets.cutoffs) {
    assert.equal(hypothesisTag(`cutoff:${cutoff}`)?.semantic_role, "CUTOFF");
  }
  for (const status of Object.keys(hypothesisFacets.statuses)) {
    assert.equal(hypothesisTag(`status:${status}`)?.semantic_role, "STATUS");
  }
});
