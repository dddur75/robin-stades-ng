import { expect, test } from "@playwright/test";
import type { PilotSnapshot } from "../app/lib/tipsters-pilot";

const authorId = "a".repeat(64);
const fixture = { id: "synthetic-match", label: "Équipe A – Équipe B", kickoff: "2026-11-28T19:00:00Z" };
const observedAt = "2026-11-28T10:00:00Z";
const snapshot: PilotSnapshot = {
  status: "ok", schemaVersion: "robin-tipsters-pilot-v1", generatedAt: observedAt,
  phase: "collecting", source: "Forecast Record", missionId: "SYNTHETIC-UI-ACCEPTANCE",
  startsAt: "2026-11-26T07:45:00Z", expiresAt: fixture.kickoff, requestsMax: 51,
  plannedSlots: 23, plannedVisits: 28, journalPresent: true, journalHead: "b".repeat(64),
  counts: { succeeded: 1, failed: 1, blocked: 1, missed: 1, running: 1, interrupted: 1, planned: 22 },
  distinctPicks: 1, lastObservationAt: observedAt, technicalVerdict: "PENDING", dossierVerdict: "PARTIAL",
  fixtures: [fixture],
  visits: ["succeeded", "failed", "blocked", "missed", "running", "interrupted", "planned"].map((status, i) => ({
    slot: `2026-11-28T${String(10 + i).padStart(2, "0")}:00:00Z`, fixtureId: fixture.id, status,
    observedAt: status === "succeeded" ? observedAt : null, picks: status === "succeeded" ? 1 : null,
  })),
  tipsters: [{ id: authorId, label: "Tipster aaaaaaaaaaaa", attributionBasis: "declared", picks: 1,
    fixtureIds: [fixture.id], firstSeenAt: observedAt, lastSeenAt: observedAt }],
  picks: [{ id: "c".repeat(64), providerId: "SYNTHETIC-PICK", fixtureId: fixture.id, authorId,
    attributionBasis: "declared", firstSeenAt: observedAt, lastSeenAt: observedAt,
    versions: [{ observedAt, detectedAt: "2026-11-28T09:00:00Z", publishedAt: null,
      market: "total", selection: "over", line: "2.5", period: "full_time", odds: null,
      sourceUrl: "https://example.invalid/synthetic-source" }] }],
  evidence: { claimId: "SYNTHETIC.UI.CLAIM", planSha256: "d".repeat(64), journalHeadSha256: "b".repeat(64), method: "synthetic" },
};

test("raccordement réel local au plan autorisé sans pronostic inventé", async ({ page, request }) => {
  const response = await request.get("/api/tipsters");
  const current = await response.json();
  test.skip(current.status === "unavailable", "Paquet A9_Mega absent sur ce runner CI");
  expect(current.status).toBe("ok");
  await page.goto("/expert/tipsters");
  await expect(page.getByRole("heading", { name: "Tipsters et pronostics" })).toBeVisible();
  if (!current.journalHead) {
    await expect(page.getByRole("heading", { name: "En attente de pronostics vérifiés" })).toBeVisible();
    await expect(page.getByText("Pronostics distincts avant match")).toBeVisible();
    await expect(page.locator(".metric-card").first().locator("strong")).toHaveText("En attente");
  }
  const denied = await request.post("/api/tipsters");
  expect(denied.status()).toBe(403);
  const outside = await request.get("/api/tipsters", { headers: { Origin: "https://example.invalid" } });
  expect(outside.status()).toBe(403);
});

test("parcours expert, recherche, fiche horodatée et téléchargement du bilan", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/tipsters", (route) => route.fulfill({ json: snapshot }));
  await page.goto("/expert");
  await page.getByRole("main").getByRole("link", { name: "Tipsters et pronostics" }).click();
  await expect(page.getByRole("heading", { name: "Tipsters en observation" })).toBeVisible();
  const search = page.getByRole("searchbox", { name: "Rechercher un tipster" });
  await search.fill("introuvable");
  await expect(page.getByRole("heading", { name: "Aucun tipster correspondant" })).toBeVisible();
  await search.fill("aaaaaaaaaaaa");
  const link = page.getByRole("link", { name: "Tipster aaaaaaaaaaaa" });
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/expert/tipsters/${authorId}$`));
  await expect(page.getByRole("heading", { name: fixture.label })).toBeVisible();
  await expect(page.getByText("Total de buts · Plus de 2.5")).toBeVisible();
  await expect(page.getByText("Première lecture avant match", { exact: true })).toBeVisible();
  await expect(page.getByText("Détection par Forecast Record", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Consulter la source" })).toHaveAttribute("href", snapshot.picks[0].versions[0].sourceUrl);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Télécharger le bilan JSON" }).click();
  const file = await downloaded;
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  expect(JSON.parse(Buffer.concat(chunks).toString())).toEqual(snapshot);
  await page.getByRole("main").getByRole("link", { name: "Suivi admin", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Journal des visites" })).toBeVisible();
  await page.getByRole("combobox", { name: "État des visites" }).selectOption("missed");
  await expect(page.getByRole("cell", { name: "Créneau manqué", exact: true })).toBeVisible();
  await page.route("**/api/tipsters", (route) => route.fulfill({ status: 503, json: { status: "invalid", message: "Preuve invalide" } }));
  await page.getByRole("button", { name: "Actualiser le suivi" }).click();
  await expect(page.getByRole("alert")).toContainText("Dernier suivi vérifié conservé");
  await expect(page.getByRole("button", { name: "Télécharger le bilan JSON" })).toBeDisabled();
  expect(errors).toEqual([]);
});

test("API distante indisponible rend un état explicite", async ({ page }) => {
  await page.route("**/api/tipsters", (route) => route.fulfill({ status: 404, contentType: "text/html", body: "Not found" }));
  await page.goto("/expert/tipsters");
  await expect(page.getByRole("heading", { name: "Connexion au pilote local requise" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("A9_Mega");
});

test("une correction et un pilote clos restent décrits fidèlement", async ({ page }) => {
  const corrected = structuredClone(snapshot);
  corrected.picks[0].versions.push({ ...corrected.picks[0].versions[0], odds: "2.20", observedAt: "2026-11-28T12:00:00Z" });
  await page.route("**/api/tipsters", (route) => route.fulfill({ json: corrected }));
  await page.goto(`/expert/tipsters/${authorId}`);
  await expect(page.getByText("Première version observée", { exact: true })).toBeVisible();
  await page.getByText("Historique du pronostic", { exact: true }).click();
  await expect(page.getByText(/Cote 2.20/)).toBeVisible();
  await page.route("**/api/tipsters", (route) => route.fulfill({ json: {
    ...snapshot, phase: "closed", journalHead: null, tipsters: [], picks: [], distinctPicks: null,
  } }));
  await page.goto("/expert/tipsters");
  await expect(page.getByRole("heading", { name: "En attente de pronostics vérifiés" })).toBeVisible();
  await expect(page.getByText(/Le pilote commencera/)).toHaveCount(0);
});

for (const width of [360, 375, 390, 430]) {
  test(`fiches et admin à ${width} px, clavier et zoom 200 %`, async ({ page }) => {
    await page.route("**/api/tipsters", (route) => route.fulfill({ json: snapshot }));
    await page.setViewportSize({ width, height: 780 });
    for (const path of ["/expert/tipsters", `/expert/tipsters/${authorId}`, "/expert/admin-collecte"]) {
      await page.goto(path);
      await expect(page.getByRole("button", { name: "Actualiser le suivi" })).toBeEnabled();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const button = page.getByRole("button", { name: "Actualiser le suivi" });
      await button.focus();
      await expect(button).toBeFocused();
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.evaluate(() => { document.body.style.zoom = "2"; });
    await expect(page.getByRole("heading", { name: "Suivi admin de la collecte" })).toBeVisible();
  });
}
