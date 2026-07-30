import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

const snapshot = JSON.parse(
  readFileSync(new URL("../app/cockpit-data.json", import.meta.url), "utf8"),
) as {
  prospectiveObservatory: {
    fixtures: {
      registry: Array<{
        fixture_id: string;
        competition: string;
        home_name: string | null;
        away_name: string | null;
        home_team_id: string;
        away_team_id: string;
        cancelled: boolean;
        status: string;
      }>;
    };
  };
};

const firstFixture = snapshot.prospectiveObservatory.fixtures.registry[0];
const matchId = firstFixture.fixture_id;
const unresolvedTeam = "Équipe en cours d’identification";
const matchHome = firstFixture.home_name ?? unresolvedTeam;
const matchAway = firstFixture.away_name ?? unresolvedTeam;
const homeHeading = "Robin suit les cinq grands championnats";
const outputRoot = ".ci/visual-regression/captures";

const routes = [
  ["accueil", "/robin-live", homeHeading],
  ["matchs", "/matchs", "Les matchs observés"],
  ["fiche-match", `/matchs/${matchId}`, `${matchHome} – ${matchAway}`],
  ["observatoire", "/observatoire", "Observatoire des données"],
  ["apprentissage", "/apprentissage", "Apprentissage en direct"],
  ["laboratoire", "/laboratoire", "Hypothèses et découvertes"],
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
      page.evaluate(() => {
        const root = document.documentElement;
        if (root.scrollWidth <= root.clientWidth) return "BOUNDED";
        const offenders = [...document.querySelectorAll<HTMLElement>("body *")]
          .map((element) => {
            const bounds = element.getBoundingClientRect();
            return {
              tag: element.tagName,
              className: element.className,
              left: Math.round(bounds.left),
              right: Math.round(bounds.right),
              width: Math.round(bounds.width),
            };
          })
          .filter((item) => item.left < 0 || item.right > root.clientWidth)
          .slice(0, 8);
        return JSON.stringify({
          clientWidth: root.clientWidth,
          scrollWidth: root.scrollWidth,
          offenders,
        });
      }),
    )
    .toBe("BOUNDED");
}

test.describe("captures Robin Experience V1", () => {
  test("desktop — pages publiques et états vides", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });

    for (const [name, route, heading] of routes) {
      await page.goto(route);
      await assertPageFrame(page, heading);
      if (route === "/resultats") {
        await expect(page.getByText("Aucun pari simulé pour le moment")).toBeVisible();
        await expect(page.getByText("ROI", { exact: true })).toHaveCount(0);
      }
      await page.screenshot({
        fullPage: true,
        path: `${outputRoot}/desktop-${name}.png`,
      });
    }
  });

  test("desktop — accueil Expert explicite", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.addInitScript(() => {
      localStorage.setItem("robin-experience-view-mode", "expert");
    });
    await page.goto("/robin-live");
    await assertPageFrame(page, homeHeading);
    await expect(page.getByRole("button", { name: /Vue Expert/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByText("Révision source")).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/desktop-accueil-expert.png`,
    });
  });

  test("desktop — apprentissage Expert et preuves techniques", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.addInitScript(() => {
      localStorage.setItem("robin-experience-view-mode", "expert");
    });
    await page.goto("/apprentissage");
    await assertPageFrame(page, "Apprentissage en direct");
    await expect(page.getByText("Registre des prédictions")).toBeVisible();
    await expect(page.getByText("Manifests d’entraînement")).toBeVisible();
    await expect(page.getByText("Événements du ledger")).toBeVisible();
    await expect(page.getByText("PROMOTION_LOCKED")).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/desktop-apprentissage-expert.png`,
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
        path: `${outputRoot}/mobile-${name}.png`,
      });
    }
  });

  test("mobile 360 px — apprentissage et sept destinations sans débordement", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 800, width: 360 });
    await page.goto("/apprentissage");
    await assertPageFrame(page, "Apprentissage en direct");
    const navigation = page.getByRole("navigation", { name: "Navigation mobile" });
    await expect(navigation).toBeVisible();
    await expect(navigation.getByRole("link")).toHaveCount(7);
    await expect(
      page.getByText(
        "Robin apprend uniquement après les matchs, sans modifier les prédictions déjà publiées.",
      ),
    ).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/mobile-360-apprentissage.png`,
    });
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
      path: `${outputRoot}/tablette-observatoire-glossaire.png`,
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

  test("smartphone — les neuf onglets restent accessibles", async ({ page }) => {
    await page.setViewportSize({ height: 844, width: 390 });
    await page.addInitScript(() => {
      localStorage.setItem("robin-experience-view-mode", "expert");
    });
    await page.goto(`/matchs/${matchId}`);
    await assertPageFrame(page, `${matchHome} – ${matchAway}`);
    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveCount(9);
    for (let index = 0; index < 9; index += 1) {
      await tabs.nth(index).click();
      await expect(tabs.nth(index)).toHaveAttribute("aria-selected", "true");
    }
  });

  test("zoom texte 200 % — navigation et contenu restent utilisables", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.goto("/robin-live");
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
  });

  test("Expert — aperçu technique du génome et mobile 375 px", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.addInitScript(() => {
      localStorage.setItem("robin-experience-view-mode", "expert");
    });
    await page.goto("/expert");
    await assertPageFrame(page, "Espace Expert");
    await expect(page.getByRole("heading", { name: "Explorateur des hypothèses" })).toBeVisible();
    await expect(page.getByText("700 règles Jalon 10", { exact: true })).toBeVisible();
    await expect(page.getByText("Génome universel V2")).toBeVisible();
    await expect(page.getByText("Aucune duplication complète dans Git")).toBeVisible();
    await expect(page.getByText("486")).toBeVisible();
    await expect(page.getByText("Stratégies validées")).toBeVisible();
    await page.screenshot({
      path: `${outputRoot}/desktop-hypotheses-expert.png`,
    });

    await page.setViewportSize({ height: 844, width: 375 });
    await expect(page.getByRole("navigation", { name: "Navigation mobile" })).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      )
      .toBe(true);
    await page.screenshot({
      path: `${outputRoot}/mobile-375-hypotheses-expert.png`,
    });
  });

  test("état snapshot modifié — preuve visuelle synthétique", async ({ page }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await page.goto("/robin-live");
    await assertPageFrame(page, homeHeading);
    await page.evaluate(() => {
      const main = document.querySelector("main");
      const banner = document.createElement("aside");
      banner.className = "evidence-note";
      banner.dataset.visualFixture = "snapshot-modifie";
      banner.innerHTML = "<span aria-hidden=\"true\">i</span><p><strong>Fixture visuelle synthétique</strong> — une nouvelle capture de blessure fait progresser le gate.</p>";
      main?.prepend(banner);
      for (const card of document.querySelectorAll(".metric-card")) {
        if (card.textContent?.includes("Preuves physiques")) {
          const value = card.querySelector(":scope > strong");
          if (value) value.textContent = "19";
        }
        if (card.textContent?.includes("Observations profondes")) {
          const value = card.querySelector(":scope > strong");
          if (value) value.textContent = "1";
        }
      }
    });
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/desktop-etat-snapshot-modifie.png`,
    });
  });

  test("état vide mobile — fixture visuelle synthétique", async ({ page }) => {
    await page.setViewportSize({ height: 844, width: 390 });
    await page.goto("/matchs");
    await assertPageFrame(page, "Les matchs observés");
    await page.evaluate(() => {
      const matchesGrid = document.querySelector(".matches-grid");
      if (!matchesGrid) {
        throw new Error("La grille des matchs hydratée est introuvable.");
      }
      const empty = document.createElement("section");
      empty.className = "empty-state";
      empty.dataset.visualFixture = "zero-fixture";
      empty.innerHTML = "<span class=\"empty-state-mark\" aria-hidden=\"true\">○</span><div><h3>Aucune rencontre suivie</h3><p>Le registre prospectif ne contient actuellement aucune fixture active.</p></div>";
      matchesGrid.replaceWith(empty);
    });
    const emptyFixture = page.locator(
      '[data-visual-fixture="zero-fixture"]',
    );
    await expect(emptyFixture).toBeVisible();
    await expect(
      emptyFixture.getByRole("heading", { name: "Aucune rencontre suivie" }),
    ).toBeVisible();
    await page.screenshot({
      fullPage: true,
      path: `${outputRoot}/mobile-etat-vide.png`,
    });
    await expect(emptyFixture).toBeVisible();
  });
});
