import assert from "node:assert/strict";
import { mkdtemp, writeFile, unlink, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import test from "node:test";
import { parseQualificationSnapshot, platformQualificationResultIds, qualificationAnchorTarget, qualificationAdminHref, qualificationCount, qualificationResults } from "../app/lib/tipster-qualification";
import { qualificationMiddleware, readQualificationSnapshot } from "../scripts/tipster-qualification-plugin";

function fixture() {
  return { schemaVersion: "robin-source-qualification-v1", capturedAt: "2026-11-22T01:53:04Z", coverage: "partial",
    results: [{ id: "olbg-642100", label: "OLBG · profil 642100", checkedAt: "2026-11-22T01:53:03Z", dateKind: "observation",
      outcome: "no_eligible", summary: "Aucun candidat parmi dix rencontres ciblées.", scope: "10 rencontres L1",
      nextStep: "Contrôle clos, aucun nouvel essai.", metrics: { requests: 3, nativeRecords: 8,
        footballRecords: 1, candidates: 0, admitted: 0 }, claims: ["ENG.SOURCE.TEST.20261122"] }] };
}

test("les inconnus restent distincts des zéros réellement mesurés", () => {
  assert.equal(qualificationCount(null), "Non mesuré");
  assert.equal(qualificationCount(0), "0");
  const value = fixture();
  const parsed = parseQualificationSnapshot(value);
  assert.equal(parsed.results[0].metrics.candidates, 0);
  assert.equal(parsed.coverage, "partial");
});

test("le contrat refuse données brutes, états actifs et preuves ou dates invalides", () => {
  const cases: unknown[] = [
    { ...fixture(), coverage: "complete" }, { ...fixture(), rawBody: "private" },
    { ...fixture(), capturedAt: "tomorrow" },
    { ...fixture(), capturedAt: "2026-02-31T01:53:04Z" },
    { ...fixture(), results: [{ ...fixture().results[0], dateKind: "publication" }] },
    { ...fixture(), results: [{ ...fixture().results[0], outcome: "active" }] },
    { ...fixture(), results: [{ ...fixture().results[0], outcome: ["no_eligible"] }] },
    { ...fixture(), results: [{ ...fixture().results[0], claims: [] }] },
    { ...fixture(), results: [{ ...fixture().results[0], claims: ["https://example.invalid"] }] },
    { ...fixture(), results: [{ ...fixture().results[0], rawFacts: [] }] },
    { ...fixture(), results: [{ ...fixture().results[0], metrics: { ...fixture().results[0].metrics, candidates: -1 } }] },
    { ...fixture(), results: [fixture().results[0], fixture().results[0]] },
    { ...fixture(), results: Array.from({ length: 51 }, (_, id) => ({ ...fixture().results[0], id: `source-${id}` })) },
  ];
  for (const value of cases) assert.throws(() => parseQualificationSnapshot(value));
});

test("le lecteur local échoue fermé sur absence, corruption et dépassement de taille", async () => {
  const directory = await mkdtemp(join(tmpdir(), "robin-qualification-"));
  const path = join(directory, "snapshot.json");
  try {
    await assert.rejects(readQualificationSnapshot(path));
    await writeFile(path, JSON.stringify(fixture()));
    assert.equal((await readQualificationSnapshot(path)).results[0].metrics.nativeRecords, 8);
    await writeFile(path, "{");
    await assert.rejects(readQualificationSnapshot(path));
    await writeFile(path, " ".repeat(131_073));
    await assert.rejects(readQualificationSnapshot(path));
  } finally { await unlink(path).catch(() => {}); await rmdir(directory); }
});

test("l'endpoint est local, GET seulement, sans cache et indisponible sans preuve", async () => {
  let reads = 0;
  const middleware = qualificationMiddleware(async () => { reads++; return parseQualificationSnapshot(fixture()); });
  const server = createServer((request, response) => { void middleware(request, response, () => { response.statusCode = 404; response.end(); }); });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;
  try {
    const ok = await fetch(`${base}/api/tipsters/qualification`);
    assert.equal(ok.status, 200);
    assert.equal(ok.headers.get("cache-control"), "no-store");
    assert.equal((await ok.json()).status, "ok");
    for (const options of [{ method: "POST" }, { headers: { origin: "https://example.invalid" } },
      { headers: { "sec-fetch-site": "cross-site" } }]) {
      assert.equal((await fetch(`${base}/api/tipsters/qualification`, options)).status, 403);
    }
    assert.equal(reads, 1);
    assert.equal((await fetch(`${base}/other`)).status, 404);
  } finally { server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); }
  const failed = qualificationMiddleware(async () => { throw new Error("private path must not leak"); });
  const unavailableServer = createServer((request, response) => { void failed(request, response, () => {}); });
  await new Promise<void>((resolve) => unavailableServer.listen(0, "127.0.0.1", resolve));
  const unavailableAddress = unavailableServer.address();
  assert.ok(unavailableAddress && typeof unavailableAddress === "object");
  try {
    const result = await fetch(`http://127.0.0.1:${unavailableAddress.port}/api/tipsters/qualification`);
    assert.equal(result.status, 503);
    assert.equal((await result.text()).includes("private path"), false);
  } finally { unavailableServer.closeAllConnections(); await new Promise<void>((resolve) => unavailableServer.close(() => resolve())); }
});


test("un lot qualifié distingue les candidats des nouveaux choix ajoutés", () => {
  const value = fixture();
  value.results[0].outcome = "qualified";
  value.results[0].metrics.candidates = 42;
  value.results[0].metrics.admitted = 1;
  const parsed = parseQualificationSnapshot(value);
  assert.equal(parsed.results[0].outcome, "qualified");
  assert.equal(parsed.results[0].metrics.candidates, 42);
  assert.equal(parsed.results[0].metrics.admitted, 1);
  assert.equal(parsed.coverage, "partial");
});


test("le contexte technique utilise seulement les identités explicites de la plateforme", () => {
  assert.deepEqual(platformQualificationResultIds("Coteur"), ["coteur-lecture-technique-20261124"]);
  assert.deepEqual(platformQualificationResultIds("NotBetting"), ["notbetting"]);
  for (const platform of ["coteur", "NotBetting clone", "Telegram", "OLBG", "https://www.coteur.com/"]) {
    assert.deepEqual(platformQualificationResultIds(platform), []);
  }
  assert.equal(qualificationAdminHref("notbetting"), "/expert/admin-collecte#qualification-notbetting");
  assert.throws(() => qualificationAdminHref("../../other"));
});

test("un contexte absent ne récupère jamais une preuve par libellé ou par défaut", () => {
  const value = fixture();
  value.results.push({ ...value.results[0], id: "notbetting", label: "Same platform text" });
  const snapshot = parseQualificationSnapshot(value);
  assert.deepEqual(qualificationResults(snapshot, []).map((row) => row.id), []);
  assert.deepEqual(qualificationResults(snapshot, ["unknown"]).map((row) => row.id), []);
  assert.deepEqual(qualificationResults(snapshot, ["notbetting"]).map((row) => row.id), ["notbetting"]);
  assert.equal(qualificationResults(snapshot).length, 2);
  assert.deepEqual(qualificationResults(snapshot).map((row) => row.id), ["olbg-642100", "notbetting"]);
  assert.equal(qualificationResults(snapshot, ["notbetting", "notbetting"]).length, 1);
  assert.equal(snapshot.results[1].metrics.admitted, 0);
});

test("les contrôles les plus récents sont visibles sans réécrire les observations", () => {
  const value = fixture();
  value.capturedAt = "2026-11-24T05:00:00Z";
  value.results.push({ ...value.results[0], id: "notbetting", checkedAt: "2026-11-24T04:00:00Z" });
  const snapshot = parseQualificationSnapshot(value);
  const before = JSON.stringify(snapshot);
  assert.deepEqual(qualificationResults(snapshot).map((row) => row.id), ["notbetting", "olbg-642100"]);
  assert.equal(JSON.stringify(snapshot), before);
  assert.equal(qualificationCount(null), "Non mesuré");
});


test("une ancre différée vise seulement une ligne connue après chargement", () => {
  const rows = parseQualificationSnapshot(fixture()).results;
  assert.equal(qualificationAnchorTarget("#qualification-olbg-642100", rows), "qualification-olbg-642100");
  assert.equal(qualificationAnchorTarget("#qualification-olbg-642100", []), null);
  for (const hash of ["", "#other", "#qualification-unknown", "#qualification-olbg-642100?x=1", "##qualification-olbg-642100", "#qualification-../../other", "#qualification-OLBG-642100"]) {
    assert.equal(qualificationAnchorTarget(hash, rows), null);
  }
});
