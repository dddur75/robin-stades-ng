import assert from "node:assert/strict";
import test from "node:test";

import {
  isExperiencePageSize,
  isHistoricalMatchDetail,
  isHistoricalMatchSummary,
  isProspectiveMatchDetail,
  isProspectiveMatchSummary,
  type HistoricalMatchDetailContract,
  type ProspectiveMatchDetailContract,
} from "../app/lib/contracts/experience-v12";

const provenance = {
  generatedAt: "2026-07-30T10:00:00Z",
  sourceContracts: ["fixture-registry"],
  sourceHashes: ["a".repeat(64)],
  sourceRevision: "revision-test",
} as const;

const teams = {
  away: {
    id: "away",
    identityStatus: "verified" as const,
    name: "Équipe extérieure",
  },
  home: {
    id: "home",
    identityStatus: "verified" as const,
    name: "Équipe domicile",
  },
};

const score = {
  away: 1,
  home: 2,
  penaltiesAway: null,
  penaltiesHome: null,
  period: "full_time" as const,
};

const historical: HistoricalMatchDetailContract = {
  schemaVersion: "match-detail-v1.2",
  phase: "historical",
  summary: {
    ...teams,
    competition: "Ligue 1",
    hypothesisRelations: [],
    id: "historical-1",
    kickoffAt: "2026-07-20T18:00:00Z",
    phase: "historical",
    score,
    settledAt: "2026-07-20T20:00:00Z",
    status: "finished",
  },
  historical: {
    eventIds: [],
    score,
    settledAt: "2026-07-20T20:00:00Z",
    statistics: {},
  },
  provenance,
};

const prospective: ProspectiveMatchDetailContract = {
  schemaVersion: "match-detail-v1.2",
  phase: "prospective",
  summary: {
    ...teams,
    competition: "Ligue 1",
    coverage: 0.5,
    dataStatus: "PARTIAL",
    hypothesisRelations: [],
    id: "prospective-1",
    kickoffAt: "2026-08-20T18:00:00Z",
    nextCaptureAt: "2026-08-19T18:00:00Z",
    nextCaptureFamilies: ["LINEUP"],
    phase: "prospective",
    status: "scheduled",
  },
  prospective: {
    capturedFamilies: ["FIXTURE"],
    captureWindows: [],
    expectedFamilies: ["LINEUP"],
    oddsSnapshotIds: [],
  },
  provenance,
};

test("les tailles de page V1.2 sont strictement bornées à 25 ou 50", () => {
  assert.equal(isExperiencePageSize(25), true);
  assert.equal(isExperiencePageSize(50), true);
  assert.equal(isExperiencePageSize(10), false);
  assert.equal(isExperiencePageSize(100), false);
  assert.equal(isExperiencePageSize("25"), false);
});

test("les résumés et détails discriminent historique et prospectif", () => {
  assert.equal(isHistoricalMatchDetail(historical), true);
  assert.equal(isProspectiveMatchDetail(historical), false);
  assert.equal(isHistoricalMatchSummary(historical.summary), true);
  assert.equal(isProspectiveMatchSummary(historical.summary), false);

  assert.equal(isProspectiveMatchDetail(prospective), true);
  assert.equal(isHistoricalMatchDetail(prospective), false);
  assert.equal(isProspectiveMatchSummary(prospective.summary), true);
  assert.equal(isHistoricalMatchSummary(prospective.summary), false);
});

test("une fiche historique ne reçoit pas de bloc prospectif et inversement", () => {
  assert.equal("prospective" in historical, false);
  assert.equal("historical" in prospective, false);
  assert.deepEqual(historical.historical.score, historical.summary.score);
  assert.deepEqual(
    prospective.prospective.expectedFamilies,
    prospective.summary.nextCaptureFamilies,
  );
});
