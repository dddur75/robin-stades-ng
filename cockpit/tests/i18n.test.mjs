import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const appRoot = new URL("../app/", import.meta.url);

function keysFrom(source) {
  return new Set(
    [...source.matchAll(/^\s*"([^"]+)":\s*/gm)].map((match) => match[1]),
  );
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const url = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
    if (entry.isDirectory()) files.push(...await sourceFiles(url));
    else if (/\.(?:ts|tsx)$/.test(entry.name)) files.push(url);
  }
  return files;
}

test("les catalogues français et anglais ont les mêmes clés", async () => {
  const [fr, en] = await Promise.all([
    readFile(new URL("../app/i18n/fr-FR.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/i18n/en-GB.ts", import.meta.url), "utf8"),
  ]);
  assert.deepEqual([...keysFrom(en)].sort(), [...keysFrom(fr)].sort());
  assert.match(en, /englishCataloguePublic = false/);
});

test("chaque clé statique utilisée existe dans le catalogue français", async () => {
  const fr = await readFile(new URL("../app/i18n/fr-FR.ts", import.meta.url), "utf8");
  const catalogue = keysFrom(fr);
  const files = await sourceFiles(appRoot);
  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(/\bt\("([^"]+)"/g)) {
      assert.ok(catalogue.has(match[1]), `${match[1]} manque dans ${file.pathname}`);
    }
  }
});

test("le catalogue français conserve accents, apostrophes et pluriels", async () => {
  const fr = await readFile(new URL("../app/i18n/fr-FR.ts", import.meta.url), "utf8");
  assert.match(fr, /État/);
  assert.match(fr, /l’essentiel/);
  assert.match(fr, /rencontres/);
  assert.match(fr, /Aucun pari simulé/);
  assert.doesNotMatch(fr, /Ã.|â€™|Â·/);
});

test("les composants publics ne réintroduisent pas les anciens titres anglais", async () => {
  const files = await sourceFiles(new URL("../app/components/", import.meta.url));
  const source = (
    await Promise.all(files.map((file) => readFile(file, "utf8")))
  ).join("\n");
  assert.doesNotMatch(
    source,
    /Command Center|Coverage Explorer|Odds Explorer|Match Center|Shadow Performance|Data Explorer|Feature Lab|Model Lab|Matchup Lab|Backtest Explorer/,
  );
});

test("le catalogue des statuts contient une présentation complète", async () => {
  const source = await readFile(
    new URL("../app/i18n/status-translations.ts", import.meta.url),
    "utf8",
  );
  for (const status of [
    "BLOCKED_BY_COVERAGE",
    "BLOCKED_BY_TEMPORALITY",
    "WAITING_FOR_OBSERVATIONS",
    "LIVE_PROSPECTIVE_CAPTURE",
    "PRODUCTION_LOCKED",
    "STORAGE_PAUSED",
    "NO_CANDIDATE",
    "NOT_DUE",
  ]) {
    assert.match(source, new RegExp(`${status}: \\{`));
  }
  assert.match(source, /short:/);
  assert.match(source, /long:/);
  assert.match(source, /tone:/);
  assert.match(source, /icon:/);
  assert.match(source, /severity:/);
});
