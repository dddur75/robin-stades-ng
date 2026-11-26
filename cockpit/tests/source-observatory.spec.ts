import { expect, test } from "@playwright/test";

test("accède au suivi des tipsters au clavier depuis l’Espace Expert", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const errors: Error[] = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.goto("/expert");
  const main = page.getByRole("main");
  const action = main.getByRole("link", { name: "Observatoire des sources" });
  await expect(action).toBeVisible();
  await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  for (let step = 0; step < 35 && !(await action.evaluate((link) => link === document.activeElement)); step += 1) {
    await page.keyboard.press("Tab");
  }
  await expect(action).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/expert\/observatoire-sources$/);
  await expect(page.getByRole("heading", { name: "Observatoire des sources" })).toBeVisible();
  await expect(page.getByText("Journal du pilote indisponible")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sources du plan" })).toBeVisible();
  await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  await page.getByRole("searchbox", { name: "Rechercher une source" }).fill("SRC_001");
  await expect(main.getByRole("status")).toHaveText("1 source affichée");
  await expect(page.getByText("RueDesJoueurs", { exact: false })).toBeVisible();
  await expect(page.getByText("SRC_002", { exact: true })).toHaveCount(0);
  await main.getByRole("combobox").selectOption("a_construire");
  await expect(main.getByRole("status")).toHaveText("0 sources affichées");
  await expect(page.getByRole("heading", { name: "Aucune source correspondante" })).toBeVisible();
  expect(errors).toEqual([]);
});

for (const width of [360, 375, 390, 430]) {
  test(`affiche le suivi à ${width} px sans défilement horizontal de la page`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    await page.goto("/expert/observatoire-sources");
    await expect(page.getByRole("heading", { name: "Observatoire des sources" })).toBeVisible();
    await expect(page.getByText("Journal du pilote indisponible")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
