import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    {
      ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Cockpit Shadow shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Robin des Stades — Cockpit Shadow V1<\/title>/i);
  assert.match(html, /Command Center/);
  assert.match(html, /PRODUCTION_LOCKED/);
  assert.match(html, /LIVE SOURCE/);
  assert.match(html, /LEGACY SOURCE/);
  assert.match(html, /SHADOW COLLECTION ACTIVE/);
  assert.match(html, /Snapshots réels/);
  assert.match(html, /19[\s ]992/);
  assert.doesNotMatch(html, /LIVE_SHADOW_VALIDATED/);
  assert.doesNotMatch(html, /react-loading-skeleton/);
});

test("ships a provenance-aware, disposable static snapshot", async () => {
  const [page, layout, data, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /Odds Monitor/);
  assert.match(page, /Shadow Bets/);
  assert.match(page, /Data Quality/);
  assert.match(page, /Strategy Lab/);
  assert.match(page, /LIVE_PIPELINE_VERIFIED/);
  assert.match(page, /EN ATTENTE DE DONNÉES PROSPECTIVES/);
  assert.match(layout, /lang="fr"/);
  assert.match(layout, /images: \["\/og\.png"\]/);
  assert.match(data, /"productionStatus": "PRODUCTION_LOCKED"/);
  assert.match(data, /"shadowStatus": "SHADOW_COLLECTION_ACTIVE"/);
  assert.match(data, /"origin": "LIVE SOURCE"/);
  assert.match(data, /"origin": "LEGACY SOURCE"/);
  assert.match(data, /"stateArtifact": "shadow-state-30095263615"/);
  assert.match(data, /"snapshots": 2/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await access(new URL("../public/og.png", import.meta.url));
  try {
    assert.deepEqual(
      await readdir(new URL("../app/_sites-preview", import.meta.url)),
      [],
    );
  } catch (error) {
    assert.equal(error.code, "ENOENT");
  }
  await assert.rejects(access(new URL("package-lock.json", root)));
});
