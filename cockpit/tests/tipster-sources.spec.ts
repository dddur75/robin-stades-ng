import { expect, test } from "@playwright/test";
import type { SourceCatalogue } from "../app/components/expert/tipster-sources";

const snapshot: SourceCatalogue = {
  status: "ok", schemaVersion: "robin-tipsters-source-settings-v1",
  revision: "0".repeat(64), registrySha256: "a".repeat(64), total: 3, prepared: 0,
  counts: { a_construire: 1, manuel: 1, bloque: 1 },
  pilotProvider: { id: "FORECAST_RECORD_J12", name: "Forecast Record", requestsMax: 51, detailsHref: "/expert/admin-collecte" },
  sources: ["manuel", "a_construire", "bloque"].map((historicalState, i) => ({
    id: `SRC_00${i + 1}`, name: `Source synthétique ${i + 1}`, url: "https://example.invalid/feed",
    historicalState: historicalState as "manuel" | "a_construire" | "bloque",
    historicalCheckedAt: "2026-10-26", historicalAccess: "Flux public archivé", historicalTerms: "Conditions historiques de test",
    limits: "Disponibilité actuelle à vérifier", competitions: "Ligue 1", historicalGate: "revalidation_required",
    prepared: false, savedAt: null,
    config: { endpoint: "https://example.invalid/feed", adapter: "rss_atom", intervalMinutes: 360, requestsPerVisit: 2, notes: "" },
  })),
};

test.beforeEach(async ({ context }) => {
  // Exercise source settings independently of the local-only candidate catalogue.
  await context.route("**/api/tipsters/candidates", (route) => route.fulfill({ status: 503, json: { status: "unavailable" } }));
});

test("le registre réel conserve les 74 sources et le fournisseur du pilote séparé", async ({ page, request }) => {
  const response = await request.get("/api/tipsters/sources");
  const value = await response.json();
  test.skip(value.status === "unavailable", "Catalogue local absent de la cible hébergée");
  expect(value.status).toBe("ok");
  expect(value.total).toBe(74);
  expect(value.counts).toEqual({ a_construire: 57, manuel: 14, bloque: 3 });
  await page.goto("/expert/sources-tipsters");
  await expect(page.getByRole("heading", { name: "Registre des sources candidates" })).toBeVisible();
  await expect(page.getByText("74 sources affichées sur 74.")).toBeVisible();
  await page.getByRole("combobox", { name: "État historique" }).selectOption("bloque");
  await expect(page.getByText("3 sources affichées sur 74.")).toBeVisible();
});

test("préparation persistante, brouillons conservés et conflit entre deux fenêtres", async ({ page, context }) => {
  let current = structuredClone(snapshot);
  let saved = 0;
  await context.route("**/api/tipsters/sources", async (route) => {
    if (route.request().method() !== "PUT") return route.fulfill({ json: current });
    const payload = route.request().postDataJSON();
    if (payload.expectedRevision !== current.revision) {
      return route.fulfill({ status: 409, json: { status: "conflict", message: "Conflit de révision. Votre brouillon est conservé." } });
    }
    const source = current.sources.find((item) => item.id === payload.sourceId)!;
    source.config = payload.config;
    source.prepared = true;
    source.savedAt = "2026-11-18T12:00:00Z";
    current = { ...current, prepared: 1, revision: String(++saved).repeat(64) };
    return route.fulfill({ json: { status: "saved", sourceId: payload.sourceId, revision: current.revision } });
  });
  const second = await context.newPage();
  await page.goto("/expert/sources-tipsters");
  await second.goto("/expert/sources-tipsters");
  for (const target of [page, second]) {
    const open = target.getByRole("button", { name: "Configurer SRC_002", exact: true });
    await open.focus();
    await target.keyboard.press("Enter");
    await expect(target.locator("#source-preparation")).toBeFocused();
  }
  await page.getByLabel("Notes de préparation").fill("Première préparation");
  await second.getByLabel("Notes de préparation").fill("Brouillon de la deuxième fenêtre");
  await page.getByRole("button", { name: "Enregistrer la préparation", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Révision" })).toBeVisible();
  await second.getByRole("button", { name: "Enregistrer la préparation", exact: true }).click();
  await expect(second.getByRole("alert").filter({ hasText: "Votre brouillon est conservé" })).toBeVisible();
  await expect(second.getByRole("alert").filter({ hasText: "Le registre local des candidats est indisponible" })).toBeVisible();
  await expect(second.getByLabel("Notes de préparation")).toHaveValue("Brouillon de la deuxième fenêtre");
  await second.getByRole("button", { name: "Actualiser le registre", exact: true }).click();
  await expect(second.getByLabel("Notes de préparation")).toHaveValue("Brouillon de la deuxième fenêtre");
  await second.getByRole("button", { name: "Configurer SRC_001", exact: true }).click();
  await second.getByRole("button", { name: "Configurer SRC_002", exact: true }).click();
  await expect(second.getByLabel("Notes de préparation")).toHaveValue("Brouillon de la deuxième fenêtre");
  await second.getByRole("button", { name: "Recharger les réglages enregistrés", exact: true }).click();
  await expect(second.getByLabel("Notes de préparation")).toHaveValue("Première préparation");
  await second.getByLabel("Notes de préparation").fill("Préparation finale");
  await second.getByRole("button", { name: "Enregistrer la préparation", exact: true }).click();
  await expect(second.getByRole("status").filter({ hasText: "Révision" })).toBeVisible();
  await second.reload();
  await second.getByRole("button", { name: "Configurer SRC_002", exact: true }).click();
  await expect(second.getByLabel("Notes de préparation")).toHaveValue("Préparation finale");
  await expect(second.getByText("État historique À construire.", { exact: false })).toBeVisible();
  await second.close();
});

test("un journal invalide affiche une erreur de lecture", async ({ page }) => {
  await page.route("**/api/tipsters/sources", (route) => route.fulfill({ json: { status: "invalid", message: "Intégrité du journal invalide" } }));
  await page.goto("/expert/sources-tipsters");
  await expect(page.getByRole("alert").filter({ hasText: "Intégrité du journal invalide" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Le registre local des candidats est indisponible" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Enregistrer la préparation", exact: true })).toHaveCount(0);
});

for (const width of [360, 375, 390, 430]) {
  test(`fiche de paramétrage à ${width} px et bornes des champs`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.route("**/api/tipsters/sources", (route) => route.fulfill({ json: snapshot }));
    await page.goto("/expert/sources-tipsters");
    await page.getByRole("searchbox", { name: "Rechercher une source" }).fill("SRC_003");
    await expect(page.getByText("1 source affichée sur 3.")).toBeVisible();
    await page.getByRole("button", { name: "Configurer SRC_003", exact: true }).click();
    await page.getByLabel("Intervalle prévu entre visites, en minutes").fill("1");
    expect(await page.getByLabel("Intervalle prévu entre visites, en minutes").evaluate((field) => (field as HTMLInputElement).checkValidity())).toBe(false);
    await expect(page.getByText("État historique Bloquée.", { exact: false })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
