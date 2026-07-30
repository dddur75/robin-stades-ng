import assert from "node:assert/strict";
import test from "node:test";

import {
  canonicalizeSearchParams,
  createPaginationContract,
  mergeSearchParams,
  parseMatchListQuery,
  parseRankingListQuery,
  serializeMatchListQuery,
  serializeRankingListQuery,
} from "../app/lib/query-params";

test("la requête matchs normalise les alias et rejette les valeurs non bornées", () => {
  const parsed = parseMatchListQuery({
    competition: "  Ligue   1 ",
    date: "2026-02-30",
    page: "99999",
    pageSize: "50",
    phase: "historical",
    q: "  gardien   absent ",
    statut: " partial ",
    tri: "team-asc",
  });

  assert.deepEqual(parsed, {
    competition: "Ligue 1",
    date: null,
    page: 10_000,
    pageSize: 50,
    phase: "historical",
    query: "gardien absent",
    sort: "team-asc",
    status: "PARTIAL",
  });
});

test("les valeurs invalides retombent sur une première page de 25", () => {
  const parsed = parseMatchListQuery(
    new URLSearchParams("page=-2&taille=100&phase=future&tri=aléatoire"),
  );
  assert.equal(parsed.page, 1);
  assert.equal(parsed.pageSize, 25);
  assert.equal(parsed.phase, "all");
  assert.equal(parsed.sort, "kickoff-asc");
});

test("la sérialisation matchs est canonique et omet les défauts", () => {
  const query = parseMatchListQuery(
    new URLSearchParams(
      "tri=kickoff-desc&taille=50&page=2&competition=Serie+A&phase=prospective",
    ),
  );
  assert.equal(
    serializeMatchListQuery(query).toString(),
    "competition=Serie+A&page=2&phase=prospective&taille=50&tri=kickoff-desc",
  );
});

test("la requête classements rejette les dimensions sans source et conserve les filtres", () => {
  const query = parseRankingListQuery(
    new URLSearchParams(
      "origine=machine_discovered&famille=market&categorie=prospective_observation&tri=risk-asc",
    ),
  );
  assert.equal(query.family, "MARKET");
  assert.equal(query.origin, "MACHINE_DISCOVERED");
  assert.equal(query.category, "historical_raw");
  assert.equal(query.sort, "roi-desc");
  assert.equal(
    serializeRankingListQuery(query).toString(),
    "famille=MARKET&origine=MACHINE_DISCOVERED",
  );

  for (const category of [
    "exploratory_priority",
    "prospective_observation",
    "validated",
    "long_tail",
  ]) {
    assert.equal(
      parseRankingListQuery(
        new URLSearchParams(`categorie=${category}`),
      ).category,
      "historical_raw",
    );
  }

  for (const sort of ["rank-asc", "result-desc", "risk-asc"]) {
    assert.equal(
      parseRankingListQuery(new URLSearchParams(`tri=${sort}`)).sort,
      "roi-desc",
    );
  }
});

test("les cinq tris historiques implémentés sont les seuls à être sérialisés", () => {
  for (const sort of [
    "roi-desc",
    "profit-desc",
    "support-desc",
    "hit-rate-desc",
    "drawdown-asc",
  ] as const) {
    const query = parseRankingListQuery(
      new URLSearchParams(`categorie=historical_raw&tri=${sort}`),
    );
    assert.equal(query.category, "historical_raw");
    assert.equal(query.sort, sort);
    assert.equal(
      serializeRankingListQuery(query).toString(),
      sort === "roi-desc" ? "" : `tri=${sort}`,
    );
  }
});

test("la canonicalisation trie clés et valeurs sans perdre les répétitions", () => {
  const params = new URLSearchParams("z=2&a=3&a=1");
  assert.equal(canonicalizeSearchParams(params).toString(), "a=1&a=3&z=2");
  assert.equal(
    mergeSearchParams(params, { page: 2, z: null }).toString(),
    "a=1&a=3&page=2",
  );
});

test("la pagination borne la page et décrit correctement les collections vides", () => {
  assert.deepEqual(createPaginationContract(99, 25, 51), {
    from: 51,
    hasNext: false,
    hasPrevious: true,
    page: 3,
    pageSize: 25,
    to: 51,
    totalItems: 51,
    totalPages: 3,
  });
  assert.deepEqual(createPaginationContract(4, 50, 0), {
    from: 0,
    hasNext: false,
    hasPrevious: false,
    page: 1,
    pageSize: 50,
    to: 0,
    totalItems: 0,
    totalPages: 1,
  });
});
