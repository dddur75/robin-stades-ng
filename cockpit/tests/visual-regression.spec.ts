import { expect, test, type Page } from "@playwright/test";

const matchId = "600aeb3560814afc9a02bec5126b249d";
const outputRoot = ".ci/visual-regression/captures";

const routes = [
  ["accueil", "/robin-live", "Robin observe actuellement 9 rencontres"],
  ["matchs", "/matchs", "Les matchs observés"],
  ["fiche-match", `/matchs/${matchId}`, "Marseille – Strasbourg"],
  ["observatoire", "/observatoire", "Observatoire des données"],
  ["laboratoire", "/laboratoire", "Laboratoire des hypothèses"],
  ["resultats", "/resultats", "Résultats"],
  ["methode", "/methode", "Comment Robin travaille"],
] as const;

async function assertPageFrame(page: Page, heading: string) {
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
}

test.describe("captures Robin Experience V1", () => {
  test("desktop — pages publiques et états vides", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });

    for (const [name, route, heading] of routes) {
      await page.goto(route);
      await assertPageFrame(page, heading);
      if (route === "/resultats") {
        await expect(page.getByText("Aucun pari simulé pour le moment")).toBeVisible();
        await expect(page.getByText("Non applicable").first()).toBeVisible();
      }
      await page.screenshot({
        fullPage: true,
        path: `${outputRoot}/desktop-${name}-1440x900.png`,
      });
    }
  });

  test("desktop — accueil Expert explicite", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.addInitScript(() => {
      localStorage.setItem("robin-experience-view-mode", "expert");
    });
    await page.goto("/robin-live");
    await assertPageFrame(page, "Robin observe actuellement 9 rencontres");
    await expect(page.getByRole("button", { name: "Vue expert" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByText("Révision source")).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/desktop-accueil-expert-1440x900.png`,
    });
  });

  test("mobile — navigation, contenus longs et absence de débordement", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 844, width: 390 });

    for (const [name, route, heading] of routes) {
      await page.goto(route);
      await assertPageFrame(page, heading);
      await expect(page.getByRole("navigation", { name: "Navigation mobile" })).toBeVisible();
      await page.screenshot({
        fullPage: true,
        path: `${outputRoot}/mobile-${name}-390x844.png`,
      });
    }
  });

  test("tablette — matrice de couverture et glossaire", async ({ page }) => {
    await page.setViewportSize({ height: 1024, width: 768 });
    await page.goto("/observatoire");
    await assertPageFrame(page, "Observatoire des données");
    await page.getByRole("button", { name: "Glossaire Robin" }).click();
    await expect(page.getByRole("dialog", { name: "Glossaire Robin" })).toBeVisible();
    await expect(page.getByText("Score de Brier").first()).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/tablette-observatoire-glossaire-768x1024.png`,
    });
  });

  test("parcours clavier — lien d’évitement et focus visible", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.goto("/robin-live");
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Aller au contenu principal" });
    await expect(skipLink).toBeFocused();
    await expect(skipLink).toHaveCSS("outline-style", "solid");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });
});
