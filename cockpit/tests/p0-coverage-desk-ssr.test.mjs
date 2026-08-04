import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

async function render(path) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("p0-coverage-test", String(Date.now()));
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost" + path, {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

function visibleText(html) {
  return html
    .replace(/<script\b[\s\S]*?<\/script>/giu, " ")
    .replace(/<style\b[\s\S]*?<\/style>/giu, " ")
    .replace(/<[^>]+>/gu, " ")
    .replace(/\s+/gu, " ");
}

test("rend le Desk P0 en SSR avec ses limites et son parcours fermé", async () => {
  const response = await render("/expert/qualite-donnees");
  assert.equal(response.status, 200);
  const html = await response.text();
  const text = visibleText(html);
  assert.match(html, /<html lang="fr-FR"/);
  assert.match(html, /Desk de couverture P0/);
  assert.match(html, /Définition E0 fermée/);
  assert.match(html, /Preuve empirique ouverte/);
  assert.match(html, />480</);
  assert.match(html, />0\/17</);
  assert.match(html, />0\/8</);
  assert.match(html, /href="#coverage-p0-table"/);
  assert.match(html, /href="#gates-calendar-fatigue"/);
  assert.match(html, /aria-disabled="true">Stratégie/);
  assert.match(html, /aria-disabled="true">Matchs/);
  assert.match(html, /Pourquoi est-il affiché/);
  assert.match(html, /Sur quelles données repose-t-il/);
  assert.match(html, /Qu’est-ce qui pourrait l’invalider/);
  assert.match(html, /Est-il historique, reconstruit ou prospectif/);
  assert.match(html, /A-t-il survécu aux corrections statistiques/);
  assert.match(html, /Non mesuré/);
  assert.match(html, /Projection sanitisée/);
  assert.match(text, /0 appel fournisseur/);

  const start = text.indexOf("Desk de couverture P0");
  const end = text.indexOf("Diagnostics sémantiques du catalogue", start);
  assert.ok(start >= 0 && end > start);
  const deskText = text.slice(start, end);
  assert.doesNotMatch(
    deskText,
    /\b(?:ROI|profit|drawdown|cote|classement|comparateur)\b/iu,
  );
  assert.doesNotMatch(
    html,
    /p0-denominator-private-projection-v1|SANITIZED_IN_PRIVATE_PROJECTION|cell_id/,
  );
});

test("la projection P0 n'est présente dans aucun asset client", async () => {
  const assets = new URL("../dist/client/assets/", import.meta.url);
  const files = (await readdir(assets)).filter((file) => file.endsWith(".js"));
  const source = (
    await Promise.all(files.map((file) => readFile(new URL(file, assets), "utf8")))
  ).join("\n");
  assert.doesNotMatch(
    source,
    /p0-denominator-private-projection-v1|SANITIZED_IN_PRIVATE_PROJECTION|cde09572da32a6b696d36c3cd5ac57ce/,
  );
});
