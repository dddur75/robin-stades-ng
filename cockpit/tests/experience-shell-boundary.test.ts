import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { getShellSummary } from "../app/lib/presentation.server";

const clientUrl = new URL(
  "../app/components/navigation/experience-shell-client.tsx",
  import.meta.url,
);
const wrapperUrl = new URL(
  "../app/components/navigation/experience-shell.tsx",
  import.meta.url,
);

test("le résumé serveur du shell reste plat, minimal et immuable", () => {
  const summary = getShellSummary();
  assert.deepEqual(Object.keys(summary).sort(), [
    "fixtures",
    "freshnessStatus",
    "generatedAt",
  ]);
  assert.equal(Number.isInteger(summary.fixtures), true);
  assert.ok(summary.fixtures >= 0);
  assert.ok(summary.generatedAt);
  assert.ok(summary.freshnessStatus);
  assert.equal(Object.isFrozen(summary), true);
});

test("le composant client ne dépend jamais de la présentation monolithique", async () => {
  const [clientSource, wrapperSource] = await Promise.all([
    readFile(clientUrl, "utf8"),
    readFile(wrapperUrl, "utf8"),
  ]);

  assert.doesNotMatch(
    clientSource,
    /(?:cockpit-presentation\.json|from\s+["'][^"']*\/presentation["'])/u,
  );
  assert.match(clientSource, /^"use client";/u);
  assert.doesNotMatch(wrapperSource, /^"use client";/u);
  assert.match(wrapperSource, /getShellSummary\(\)/u);
});
