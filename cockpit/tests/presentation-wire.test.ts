import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { decodePresentationWire, encodePresentationWire } from "../app/lib/presentation-wire";

function fixture() {
  return {
    generatedAt: "2026-11-21T00:00:00Z",
    dashboard: { flags: [true, false], errors: [{ code: "KEEP" }], policyVersion: "root-metadata" },
    system: { locked: true, realBets: false, nullable: null },
    matches: [
      { id: "fixture-a", unknown: { score: 0 }, timeline: [
        { id: "one", policyVersion: "alpha", status: "OPEN", active: true, acknowledged: false, metadata: { veto: null } },
        { id: "two", policyVersion: "beta", status: "BLOCKED", active: false, acknowledged: true, extra: ["keep", 0] },
      ] },
      { id: "fixture-b", timeline: [
        { id: "three", policyVersion: "alpha", status: "FAILED", error: "preserved" },
      ] },
    ],
    other: [{ policyVersion: "unrelated", policyVersionIndex: "also-unrelated" }],
  };
}

test("multiple policy dictionary is deterministic, lossless and leaves all input fields intact", () => {
  const source = fixture();
  const before = structuredClone(source);
  Object.freeze(source.matches[0].timeline[0]);
  Object.freeze(source.matches[0].timeline);
  Object.freeze(source.matches[0]);
  Object.freeze(source.matches);
  Object.freeze(source);
  const wire = encodePresentationWire(source);
  assert.deepEqual(wire.timelinePolicyVersions, ["alpha", "beta"]);
  assert.deepEqual(wire, {
    ...before,
    matches: before.matches.map((match) => ({
      ...match,
      timeline: match.timeline.map(({ policyVersion, ...window }) => ({
        ...window, policyVersionIndex: policyVersion === "alpha" ? 0 : 1,
      })),
    })),
    timelinePolicyVersions: ["alpha", "beta"],
  });
  const encodedBefore = structuredClone(wire);
  assert.deepEqual(decodePresentationWire(wire), before);
  assert.deepEqual(wire, encodedBefore);
  assert.deepEqual(source, before);
  assert.deepEqual(encodePresentationWire(source), wire);
});

test("empty matches and timelines use an empty dictionary without special policy constants", () => {
  for (const source of [{ matches: [] }, { matches: [{ timeline: [], metadata: false }] }]) {
    const wire = encodePresentationWire(source);
    assert.deepEqual(wire.timelinePolicyVersions, []);
    assert.deepEqual(decodePresentationWire(wire), source);
  }
});

test("encoder rejects malformed source shapes and all reserved-field collisions", () => {
  const invalid: unknown[] = [
    null, [], {}, { matches: null }, { matches: {} }, { matches: [null] },
    { matches: [{}] }, { matches: [{ timeline: {} }] },
    { matches: [{ timeline: [null] }] }, { matches: [{ timeline: [{}] }] },
    { matches: [{ timeline: [{ policyVersion: 1 }] }] },
    { matches: [], timelinePolicyVersions: [] },
    { matches: [{ timeline: [{ policyVersion: "ok", policyVersionIndex: 0 }] }] },
  ];
  for (const value of invalid) assert.throws(() => encodePresentationWire(value), /PRESENTATION_WIRE_/);
});

test("decoder rejects malformed dictionary, container and policy collisions", () => {
  const invalid: unknown[] = [
    null, [], {}, { matches: [] },
    { matches: [], timelinePolicyVersions: null },
    { matches: [], timelinePolicyVersions: {} },
    { matches: [], timelinePolicyVersions: [false] },
    { matches: [], timelinePolicyVersions: ["a", "a"] },
    { matches: [], timelinePolicyVersions: Array(1) },
    { matches: null, timelinePolicyVersions: [] },
    { matches: [null], timelinePolicyVersions: [] },
    { matches: [{}], timelinePolicyVersions: [] },
    { matches: [{ timeline: {} }], timelinePolicyVersions: [] },
    { matches: [{ timeline: [null] }], timelinePolicyVersions: [] },
    { matches: [{ timeline: [{ policyVersionIndex: 0, policyVersion: "collision" }] }], timelinePolicyVersions: ["a"] },
  ];
  for (const value of invalid) assert.throws(() => decodePresentationWire(value), /PRESENTATION_WIRE_/);
});

test("decoder rejects absent, noninteger, boolean, negative and out-of-bounds indices", () => {
  const windows: unknown[] = [
    {}, { policyVersionIndex: undefined }, { policyVersionIndex: null },
    ...[true, false, "0", 0.5, NaN, Infinity, -1, 1, Number.MAX_SAFE_INTEGER + 1].map(
      (policyVersionIndex) => ({ policyVersionIndex }),
    ),
  ];
  for (const window of windows) {
    assert.throws(() => decodePresentationWire({
      timelinePolicyVersions: ["only"], matches: [{ timeline: [window] }],
    }), /PRESENTATION_WIRE_/);
  }
  assert.throws(() => decodePresentationWire({
    timelinePolicyVersions: [], matches: [{ timeline: [{ policyVersionIndex: 0 }] }],
  }), /PRESENTATION_WIRE_/);
});

test("one already prepared projection roundtrips exactly and checked-in client wire matches it", () => {
  const source = JSON.parse(readFileSync(new URL("../app/cockpit-presentation.json", import.meta.url), "utf8"));
  const client = JSON.parse(readFileSync(new URL("../app/cockpit-presentation-client.json", import.meta.url), "utf8"));
  const before = JSON.stringify(source);
  const wire = encodePresentationWire(source);
  assert.deepEqual(decodePresentationWire(wire), source);
  assert.deepEqual(client, wire);
  assert.equal(JSON.stringify(source), before);
  assert.ok(JSON.stringify(wire).length < before.length);
});

