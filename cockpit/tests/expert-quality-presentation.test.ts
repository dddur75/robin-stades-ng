import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCurrentQualityRows,
  buildHistoricalQualityRows,
  HISTORICAL_DATA_LABEL,
  SNAPSHOT_UNVERIFIABLE_LABEL,
} from "../app/lib/expert-quality-presentation";

test("les contrôles legacy sont conservés et tous marqués comme historiques", () => {
  const checks = [
    {
      check: "PostgreSQL Neon",
      origin: "LIVE SOURCE",
      status: "PASS",
      threshold: "connecté",
      value: "101 lignes · révision 0003_jalon4_durable_shadow",
    },
    {
      check: "API-Football",
      origin: "NO OUTPUT",
      status: "PENDING",
      threshold: "optionnel",
      value: "adaptateur prêt, secret absent",
    },
  ] as const;

  const rows = buildHistoricalQualityRows(checks, {
    sourceCommit: "legacy-revision",
    stateArtifact: "legacy-artifact",
  });

  assert.equal(rows.length, checks.length);
  assert.ok(rows.every((row) => row.provenance.startsWith(HISTORICAL_DATA_LABEL)));
  assert.match(rows[0].provenance, /legacy-artifact · legacy-revision/);
  assert.equal(checks[0].value, "101 lignes · révision 0003_jalon4_durable_shadow");
});

test("l’état courant vient uniquement de la preuve opérationnelle et explicite ses limites", () => {
  const evidence = {
    generatedAt: "2026-07-29T13:01:53Z",
    sourceRevision: "current-revision",
    sourceRun: "current-run",
    freshness: { ageMinutes: 19, status: "FRESHNESS_CURRENT" },
    postgresql: {
      inserts: 733,
      lag: 0,
      migration: "0009_jalon12_observatory",
      reconstructionStatus: "REPLAY_VERIFIED",
      tables: 12,
    },
    providers: {
      apiFootballCalls: 33,
      apiFootballCap: 250,
      oddsApiCredits: 0,
      oddsApiCap: 20,
    },
    r2: {
      lag: 0,
      objects: 450,
      replayStatus: "R2_REPLAY_VERIFIED",
      verified: 450,
    },
  } as const;

  const rows = buildCurrentQualityRows(evidence);
  const postgres = rows.find((row) => row.control === "PostgreSQL");
  const apiFootball = rows.find((row) => row.control === "API-Football");
  const footballDataOrg = rows.find((row) => row.control === "football-data.org");

  assert.match(postgres?.evidence ?? "", /0009_jalon12_observatory · 12 tables · 733 insertions/);
  assert.match(apiFootball?.evidence ?? "", /33 appels enregistrés · plafond 250/);
  assert.match(apiFootball?.limits ?? "", new RegExp(SNAPSHOT_UNVERIFIABLE_LABEL, "i"));
  assert.doesNotMatch(apiFootball?.limits ?? "", /clé présente|plan gratuit|secret absent/i);
  assert.match(footballDataOrg?.evidence ?? "", /distincts de Football-Data\.co\.uk/);
  assert.equal(evidence.postgresql.migration, "0009_jalon12_observatory");
});
