import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const forbiddenPublicTerms = [
  ["Walk-forward", /\bwalk[\s-]?forward\b/iu],
  ["Backtest", /\bbacktests?\b/iu],
  ["Drawdown", /\bdrawdowns?\b/iu],
  ["Feature", /\bfeatures?\b/iu],
  ["Gate", /\bgates?\b/iu],
  ["FDR", /\bFDR\b/u],
  ["q-value", /\bq[\s-]?values?\b/iu],
  ["Beam search", /\bbeam\s+search\b/iu],
  ["Pruning", /\bpruning\b/iu],
  ["Long tail", /\blong\s+tail\b/iu],
  ["Shadow", /\bshadow\b/iu],
  ["Dataset", /\bdatasets?\b/iu],
  ["Cutoff", /\bcutoffs?\b/iu],
];

const publicRoutes = [
  "/hypotheses",
  "/hypotheses/familles",
  "/hypotheses/familles/formation-structure",
  "/hypotheses/familles/weather",
  "/hypotheses/arbres",
  "/hypotheses/J10-M001",
  "/hypotheses/H11-002",
  "/hypotheses/classements",
  "/hypotheses/observations",
  "/hypotheses/longue-traine",
];

async function render(path) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set(
    "hypothesis-vocabulary-test",
    `${process.pid}-${Date.now()}-${path}`,
  );
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request(`http://localhost${path}`, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { passThroughOnException() {}, waitUntil() {} },
  );
}

function decodeEntities(text) {
  return text
    .replaceAll("&nbsp;", " ")
    .replaceAll("&#x27;", "’")
    .replaceAll("&#39;", "’")
    .replaceAll("&quot;", '"')
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">");
}

function publicVisibleText(html) {
  return decodeEntities(
    html
      .replace(/<(?:script|style|code|pre)\b[\s\S]*?<\/(?:script|style|code|pre)>/giu, " ")
      .replace(/<[^>]+>/gu, " ")
      .replace(/\s+/gu, " "),
  );
}

function assertFrenchPublicVocabulary(text, context) {
  for (const [term, pattern] of forbiddenPublicTerms) {
    assert.doesNotMatch(text, pattern, `${context} expose « ${term} »`);
  }
}

function collectFrenchContractCopy(value, key = "") {
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectFrenchContractCopy(item, key));
  }
  if (value == null || typeof value !== "object") {
    return typeof value === "string" &&
      (key.endsWith("_fr") ||
        key === "display_name_fr" ||
        key === "display_rule_fr" ||
        key === "label_fr" ||
        key === "warning_fr")
      ? [value]
      : [];
  }
  return Object.entries(value).flatMap(([childKey, child]) =>
    collectFrenchContractCopy(child, childKey),
  );
}

test("les vues publiques rendues par défaut n’exposent pas le jargon anglais du brief", async () => {
  for (const route of publicRoutes) {
    const response = await render(route);
    assert.equal(response.status, 200, route);
    const text = publicVisibleText(await response.text());
    assertFrenchPublicVocabulary(text, route);
  }
});

test("les libellés français des contrats respectent le même vocabulaire", async () => {
  const universe = JSON.parse(
    await readFile(
      new URL("../app/hypothesis-universe-data.json", import.meta.url),
      "utf8",
    ),
  );
  const publicCopy = collectFrenchContractCopy(universe.contracts).join(" ");
  assert.ok(publicCopy.length > 1_000);
  assertFrenchPublicVocabulary(publicCopy, "contrats français");
});

test("le contrôle ignore volontairement la Vue Expert, code et identifiants internes", async () => {
  const universeSource = await readFile(
    new URL("../app/hypothesis-universe-data.json", import.meta.url),
    "utf8",
  );
  assert.match(universeSource, /(?:DATA_GATE|cutoff|feature)/i);

  const response = await render("/hypotheses/J10-M001");
  const html = await response.text();
  const visibleWithoutTechnicalCode = publicVisibleText(html);
  assert.doesNotMatch(visibleWithoutTechnicalCode, /\bq[\s-]?value\b/iu);
});
