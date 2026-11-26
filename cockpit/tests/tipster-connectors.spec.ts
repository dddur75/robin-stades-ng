import { expect, test } from "@playwright/test";

const view = {
  status: "ok", schemaVersion: "robin-connectors-v1", running: false, canRun: true,
  updatedAt: "2026-11-18T12:00:00Z", journalHead: "a".repeat(64), mission: { expires_at: "2026-11-19T12:00:00Z" },
  profiles: [{ id: "SRC_006", name: "Source de recette", endpoint: "https://example.invalid/feed/", adapter: "rss_atom" }],
  sources: [], candidates: [], counts: { requests: 3, attemptedSources: 0, collectedSources: 0,
    publications: 2, candidates: 0, verifiedPreMatch: 0 },
};

test("consulter ne déclenche aucune collecte et le lancement exige une action", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/tipsters/connectors", (route) => {
    if (route.request().method() === "POST") {
      calls++;
      expect(route.request().postDataJSON()).toEqual({ sourceId: "all" });
      return route.fulfill({ status: 202, json: { status: "accepted", message: "Exécution demandée." } });
    }
    return route.fulfill({ json: view });
  });
  await page.goto("/expert/admin-collecte");
  await expect(page.getByRole("heading", { name: "Collecte des sources tipsters", exact: true })).toBeVisible();
  expect(calls).toBe(0);
  await page.getByRole("button", { name: "Vérifier les 1 sources restantes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Exécution demandée." })).toBeVisible();
  expect(calls).toBe(1);
});

for (const width of [360, 375, 390, 430]) {
  test(`suivi lisible au clavier à ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/tipsters/connectors", (route) => route.fulfill({ json: view }));
    await page.goto("/expert/admin-collecte");
    const field = page.getByRole("textbox", { name: "Rechercher un connecteur" });
    await field.focus();
    await expect(field).toBeFocused();
    await field.fill("absent");
    await expect(page.getByRole("link", { name: "Source de recette" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("un journal expiré interdit le lancement et une source refusée reste visible", async ({ page }) => {
  await page.route("**/api/tipsters/connectors", (route) => route.fulfill({ json: {
    ...view, canRun: false, sources: [{ sourceId: "SRC_006", status: "permission_required", publications: [], candidates: [] }],
  } }));
  await page.goto("/expert/admin-collecte");
  await expect(page.getByRole("button", { name: "Vérifier les 1 sources restantes" })).toBeDisabled();
  await expect(page.getByText("Mission expirée ou absente. Un nouveau plan est requis.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Conditions de cet accès à réexaminer" })).toBeVisible();
  await expect(page.getByText("Permission de l’éditeur requise",{exact:true})).toHaveCount(0);
});

test("les lignes et les extractions ambiguës restent explicites", async ({ page }) => {
  await page.route("**/api/tipsters/connectors", (route) => route.fulfill({ json: {
    ...view, candidates: [{ id: "test-pick", authorId: "author:123456789abcdef", sourceId: "SRC_006", market: "total",
      selection: "over", line: "2.5", extractionStatus: "non_resolu", declaredOdds: null,
      url: "https://example.invalid/prono", observedAt: "2026-11-18T12:00:00Z" }],
  } }));
  await page.goto("/expert/admin-collecte");
  await expect(page.getByText(/Total de buts : Plus de 2.5/)).toBeVisible();
  await expect(page.getByText(/Extraction ambiguë à examiner/)).toBeVisible();
});

test("une attribution ouvre sa fiche sans devenir un tipster validé", async ({ page }) => {
  const author = `author:${"b".repeat(64)}`;
  await page.route("**/api/tipsters/connectors", (route) => route.fulfill({ json: {
    ...view, publications: [{ id: "publication", sourceId: "SRC_006", authorId: author,
      contentSha256: "c".repeat(64), url: "https://example.invalid/publication", announcedAt: "2020-11-18T12:00:00Z",
      observedAt: "2026-11-18T12:00:00Z" }],
  } }));
  await page.goto("/expert/tipsters");
  await page.getByRole("link", { name: "Attribution bbbbbbbbbbbb", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Fiche d’attribution", exact: true })).toBeVisible();
  await expect(page.getByText(/Identité humaine non vérifiée/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Publication SRC_006" })).toBeVisible();
  await expect(page.getByText(/Publication déclarée : .*2020/)).toBeVisible();
  await expect(page.getByText(/Aucun pronostic vérifié avant match pour cette attribution/)).toBeVisible();
});
