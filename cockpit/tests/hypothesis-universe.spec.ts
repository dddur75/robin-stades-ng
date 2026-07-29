import { expect, test, type Page } from "@playwright/test";

type ViewMode = "analysis" | "discovery" | "expert";

const outputRoot = ".ci/visual-regression/captures";
const forbiddenPublicTerms = [
  /\bwalk[\s-]?forward\b/iu,
  /\bbacktests?\b/iu,
  /\bdrawdowns?\b/iu,
  /\bfeatures?\b/iu,
  /\bgates?\b/iu,
  /\bFDR\b/u,
  /\bq[\s-]?values?\b/iu,
  /\bbeam\s+search\b/iu,
  /\bpruning\b/iu,
  /\blong\s+tail\b/iu,
  /\bshadow\b/iu,
  /\bdatasets?\b/iu,
  /\bcutoffs?\b/iu,
];

async function useMode(page: Page, mode: ViewMode) {
  await page.addInitScript((selectedMode) => {
    window.localStorage.setItem(
      "robin-experience-view-mode",
      selectedMode,
    );
  }, mode);
}

async function openPage(page: Page, path: string, heading?: string | RegExp) {
  const response = await page.goto(path);
  expect(response?.ok(), `${path} doit répondre avec succès`).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  if (heading) {
    await expect(
      page.getByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
  }
}

async function assertNoDocumentOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const root = document.documentElement;
        return root.scrollWidth <= root.clientWidth;
      }),
    )
    .toBe(true);
}

async function capture(page: Page, name: string, fullPage = true) {
  await page.screenshot({
    animations: "disabled",
    fullPage,
    path: `${outputRoot}/${name}.png`,
  });
}

async function assertFrenchVocabulary(page: Page) {
  const publicCopy = await page.locator("body").evaluate((body) => {
    const copy = body.cloneNode(true) as HTMLElement;
    copy
      .querySelectorAll("code, pre, script, style")
      .forEach((element) => element.remove());
    const accessibleAttributes = [...copy.querySelectorAll<HTMLElement>(
      "[aria-label], [title]",
    )].flatMap((element) => [
      element.getAttribute("aria-label") ?? "",
      element.getAttribute("title") ?? "",
    ]);
    return `${copy.innerText}\n${accessibleAttributes.join("\n")}`;
  });
  for (const pattern of forbiddenPublicTerms) {
    expect(publicCopy).not.toMatch(pattern);
  }
}

test.describe("Univers des hypothèses — preuves visuelles et parcours", () => {
  test("univers — desktop, tablette, mobiles 390/360, zoom 200 % et Vue Expert", async ({
    page,
  }) => {
    await useMode(page, "discovery");

    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses", "L’Univers des hypothèses");
    await expect(page.getByText("28 grandes familles")).toBeVisible();
    await expect(page.getByText("486 propriétés football")).toBeVisible();
    await expect(
      page.getByText("Zéro stratégie validée est un résultat honnête."),
    ).toBeVisible();
    await assertNoDocumentOverflow(page);
    await capture(page, "desktop-univers");

    await page.setViewportSize({ height: 1024, width: 768 });
    await assertNoDocumentOverflow(page);
    await capture(page, "tablette-univers");

    await page.setViewportSize({ height: 844, width: 390 });
    await expect(
      page.getByRole("navigation", { name: "Navigation mobile" }),
    ).toBeVisible();
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-univers");

    await page.setViewportSize({ height: 800, width: 360 });
    await assertNoDocumentOverflow(page);

    for (const viewport of [
      { height: 812, width: 375 },
      { height: 932, width: 430 },
      { height: 1080, width: 1920 },
    ]) {
      await page.setViewportSize(viewport);
      await assertNoDocumentOverflow(page);
    }

    await page.setViewportSize({ height: 900, width: 1440 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await expect(page.getByRole("main")).toBeVisible();
    await assertNoDocumentOverflow(page);
    await capture(page, "zoom-200");

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "";
      window.localStorage.setItem("robin-experience-view-mode", "expert");
      window.dispatchEvent(
        new Event("robin-experience-view-mode-change"),
      );
    });
    await expect(
      page.getByRole("button", { name: /^Vue Expert\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Vue Expert", { exact: true }).last()).toBeVisible();
    await capture(page, "desktop-vue-expert");
  });

  test("navigation clavier — évitement, recherche et arbre paresseux", async ({
    page,
  }) => {
    await useMode(page, "discovery");
    await page.setViewportSize({ height: 900, width: 1440 });
    const nodeRequests: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/data/hypotheses/nodes/")) {
        nodeRequests.push(request.url());
      }
    });

    await openPage(page, "/hypotheses/arbres", "Les arbres d’hypothèses");
    expect(nodeRequests).toHaveLength(0);

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", {
      name: "Aller au contenu principal",
    });
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();

    const expand = page.getByRole("button", { name: /^Développer \(/ }).first();
    await expand.press("Enter");
    await expect(
      page.getByRole("button", { name: "Replier" }).first(),
    ).toHaveAttribute("aria-expanded", "true");
    await expect.poll(() => nodeRequests.length).toBeGreaterThan(0);
    await expect(page.getByText(/Pages chargées/)).toBeVisible();
    await capture(page, "desktop-arbre");
  });

  test("arbre mobile 390 px et largeur minimale 360 px", async ({ page }) => {
    await useMode(page, "discovery");
    await page.setViewportSize({ height: 844, width: 390 });
    await openPage(page, "/hypotheses/arbres", "Les arbres d’hypothèses");
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-arbre");

    await page.setViewportSize({ height: 800, width: 360 });
    await assertNoDocumentOverflow(page);
    await expect(page.getByLabel("Votre recherche")).toBeVisible();
    await expect(page.getByLabel("État matériel")).toBeVisible();
    await expect(page.getByLabel("Heure limite")).toBeVisible();
    await expect(page.getByLabel("Marché", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Profondeur")).toBeVisible();
  });

  test("facettes URL — initialisation, sérialisation et chargement borné", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    const nodeRequests: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/data/hypotheses/nodes/")) {
        nodeRequests.push(request.url());
      }
    });

    await openPage(
      page,
      "/hypotheses/arbres?famille=weather&statut=DATA_GATE_BLOCKED&cutoff=H-2&marche=NO_MARKET_REQUIRED&profondeur=1&vue=liste",
      "Les arbres d’hypothèses",
    );
    await expect(page.getByLabel("Famille")).toHaveValue("WEATHER");
    await expect(page.getByLabel("État matériel")).toHaveValue(
      "DATA_GATE_BLOCKED",
    );
    await expect(page.getByLabel("Heure limite")).toHaveValue("H-2");
    await expect(page.getByLabel("Marché", { exact: true })).toHaveValue(
      "NO_MARKET_REQUIRED",
    );
    await expect(page.getByLabel("Profondeur")).toHaveValue("1");
    await expect(
      page.getByRole("button", { name: "Vue liste" }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => nodeRequests.length).toBeGreaterThan(0);
    await expect(page.locator(".hu-filter-sentence")).toContainText(
      "Météo ET état Bloquée par les données",
    );

    await page
      .getByRole("checkbox", { name: "Afficher seulement la longue traîne" })
      .check();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("longue-traine"))
      .toBe("1");
    await page.getByLabel("Marché", { exact: true }).selectOption("1X2");
    await expect
      .poll(() => new URL(page.url()).searchParams.get("marche"))
      .toBe("1X2");
  });

  test("liste et graphe limitent le nombre de cartes rendues", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(
      page,
      "/hypotheses/arbres?vue=liste",
      "Les arbres d’hypothèses",
    );
    await expect(
      page.getByRole("button", { name: "Tous les nœuds sont chargés" }),
    ).toBeDisabled({ timeout: 15_000 });

    const cards = page.locator(".hu-node-collection-liste .hu-tree-node");
    const firstBatch = await cards.count();
    expect(firstBatch).toBeGreaterThan(0);
    expect(firstBatch).toBeLessThanOrEqual(60);
    const showMore = page.getByRole("button", {
      name: /Afficher davantage de branches/,
    });
    await expect(showMore).toBeVisible();
    await showMore.click();
    await expect.poll(() => cards.count()).toBeGreaterThan(firstBatch);
    expect(await cards.count()).toBeLessThanOrEqual(120);
  });

  test("recherche française et filtres — desktop et mobile", async ({ page }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/arbres", "Les arbres d’hypothèses");

    const search = page.getByLabel("Votre recherche");
    await search.fill("Météo ET vent fort SAUF branches bloquées");
    await search.press("Enter");
    const understood = page.locator(".hu-understood-filters");
    await expect(understood.getByText("Filtres compris par Robin")).toBeVisible();
    await expect(understood).toContainText("Météo");
    await expect(understood).toContainText("Vent fort");
    await expect(understood).toContainText("SAUF Branches bloquées");
    await expect(page).toHaveURL(/q=M%C3%A9t%C3%A9o/);
    await page.getByLabel("Famille").selectOption("WEATHER");
    await expect
      .poll(() => new URL(page.url()).searchParams.get("famille"))
      .toBe("weather");
    expect(new URL(page.url()).searchParams.get("q")).toContain("Météo");
    await assertFrenchVocabulary(page);
    await capture(page, "desktop-filtres");

    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-filtres");
  });

  test("comparateur — sélection de deux branches", async ({ page }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/arbres", "Les arbres d’hypothèses");

    const compare = page.getByRole("checkbox", { name: "Comparer" });
    await compare.nth(0).check();
    await compare.nth(1).check();
    const comparator = page.getByRole("region", {
      name: "Comparateur d’hypothèses",
    });
    await expect(comparator).toBeVisible();
    await expect(
      comparator.getByRole("heading", { name: "2 hypothèses sélectionnées" }),
    ).toBeVisible();
    await expect(comparator.getByText("Support", { exact: true })).toHaveCount(2);
    await capture(page, "desktop-comparateur");
  });

  test("catalogue et familles Formations / Météo", async ({ page }) => {
    await useMode(page, "discovery");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/familles");
    await expect(
      page.getByRole("heading", { level: 1 }).filter({ hasText: "familles" }),
    ).toBeVisible();
    await expect(page.getByText("Formations et structures").first()).toBeVisible();
    await expect(page.getByText("Météo").first()).toBeVisible();
    await capture(page, "desktop-familles");

    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-familles");

    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(
      page,
      "/hypotheses/familles/formation-structure",
      /Formations et structures/,
    );
    await capture(page, "desktop-famille-formations");

    await openPage(page, "/hypotheses/familles/weather", "Météo");
    await expect(
      page.getByText(/archive météo|données nécessaires|bloqu/i).first(),
    ).toBeVisible();
    await capture(page, "desktop-famille-meteo");
    await page.getByRole("link", { name: "Ouvrir l’explorateur" }).click();
    await expect(page).toHaveURL(/\/hypotheses\/arbres\?famille=weather/);
    await expect(page.getByLabel("Famille")).toHaveValue("WEATHER");
  });

  test("fiches J10-M001 et graine H11-002", async ({ page }) => {
    await useMode(page, "discovery");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M001", /victoire à l’extérieur/i);
    await expect(page.getByText("J10-M001", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Pourquoi ce signal n’est pas validé",
      }),
    ).toBeVisible();
    await capture(page, "desktop-fiche-j10-m001");

    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-fiche-j10-m001");

    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/H11-002", "4-3-3 contre 4-4-2");
    await expect(page.getByText("Piste proposée par David")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Cette graine génère un arbre complet de combinaisons.",
      }),
    ).toBeVisible();
    await capture(page, "desktop-fiche-graine-david");
  });

  test("les trois modes changent réellement le contenu et persistent après rechargement", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M001", /victoire à l’extérieur/i);

    await expect(
      page.getByRole("button", { name: /^Vue Découverte\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("heading", { name: "L’essentiel en clair" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Ce que le passé montre" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Données, contrat et provenance" }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: /^Vue Analyse\./ }).click();
    await expect(
      page.getByRole("button", { name: /^Vue Analyse\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("heading", { name: "Ce que le passé montre" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Observation prospective" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Données, contrat et provenance" }),
    ).toHaveCount(0);

    await page.reload();
    await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^Vue Analyse\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("heading", { name: "Ce que le passé montre" }),
    ).toBeVisible();

    await page.getByRole("button", { name: /^Vue Expert\./ }).click();
    await expect(
      page.getByRole("heading", { name: "Données, contrat et provenance" }),
    ).toBeVisible();
    await expect(page.locator(".hu-expert-proof code").first()).toBeVisible();

    await page.reload();
    await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^Vue Expert\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("heading", { name: "Données, contrat et provenance" }),
    ).toBeVisible();

    await page.getByRole("button", { name: /^Vue Découverte\./ }).click();
    await openPage(
      page,
      "/hypotheses/classements",
      "Classements des hypothèses",
    );
    await expect(
      page.getByRole("heading", {
        name: "Comprendre les pistes avant les chiffres",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Lire la solidité, pas seulement le rang",
      }),
    ).toHaveCount(0);

    await page.getByRole("button", { name: /^Vue Analyse\./ }).click();
    await expect(
      page.getByRole("heading", {
        name: "Comparer les preuves et leurs limites",
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: "Lire la solidité, pas seulement le rang",
      }),
    ).toBeVisible();

    const marketFilter = page.getByLabel("Marché", { exact: true });
    const originFilter = page.getByLabel("Origine", { exact: true });
    const cutoffFilter = page.getByLabel("Heure limite", { exact: true });
    await expect.poll(() => marketFilter.locator("option").count()).toBeGreaterThan(1);
    await expect.poll(() => originFilter.locator("option").count()).toBeGreaterThan(1);
    await expect.poll(() => cutoffFilter.locator("option").count()).toBeGreaterThan(1);
    await marketFilter.selectOption({ index: 1 });
    await originFilter.selectOption({ index: 1 });
    await cutoffFilter.selectOption({ index: 1 });
    await expect(page).toHaveURL(/marche=/);
    await expect(page).toHaveURL(/origine=/);
    await expect(page).toHaveURL(/heure-limite=/);

    const selectedMarket = await marketFilter.inputValue();
    const selectedOrigin = await originFilter.inputValue();
    const selectedCutoff = await cutoffFilter.inputValue();
    await page.reload();
    await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
    await expect(
      page.getByRole("button", { name: /^Vue Analyse\./ }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("Marché", { exact: true })).toHaveValue(
      selectedMarket,
    );
    await expect(page.getByLabel("Origine", { exact: true })).toHaveValue(
      selectedOrigin,
    );
    await expect(page.getByLabel("Heure limite", { exact: true })).toHaveValue(
      selectedCutoff,
    );

    await page.getByRole("button", { name: /^Vue Expert\./ }).click();
    await expect(
      page.getByRole("heading", { name: "Portée contractuelle brute" }),
    ).toBeVisible();
    await expect(
      page.locator(".hu-expert-proof code").filter({
        hasText: "hypothesis-global-rankings",
      }),
    ).toBeVisible();
    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await expect(
      page.getByLabel("Heure limite", { exact: true }),
    ).toBeVisible();
  });

  test("classements global, Liga, Serie A, zéro validée et longue traîne", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(
      page,
      "/hypotheses/classements",
      "Classements des hypothèses",
    );
    await expect(
      page.getByRole("button", { name: "Global", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await capture(page, "desktop-classement-global");

    const liga = page.getByRole("button", { name: "Liga", exact: true });
    await liga.click();
    await expect(liga).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/competition=Liga/);
    await capture(page, "desktop-classement-liga");

    const serieA = page.getByRole("button", { name: "Serie A", exact: true });
    await serieA.click();
    await expect(serieA).toHaveAttribute("aria-pressed", "true");
    await expect(page).toHaveURL(/competition=Serie(\+|%20)A/);
    await capture(page, "desktop-classement-serie-a");

    const zeroValidated = page.locator("#strategies-validees");
    await expect(
      zeroValidated.getByRole("heading", {
        name: "Aucune stratégie n’est encore scientifiquement validée",
      }),
    ).toBeVisible();
    await zeroValidated.scrollIntoViewIfNeeded();
    await zeroValidated.screenshot({
      animations: "disabled",
      path: `${outputRoot}/desktop-aucune-strategie-validee.png`,
    });

    await openPage(page, "/hypotheses/longue-traine", "La longue traîne");
    await expect(page.getByText("8", { exact: true }).first()).toBeVisible();
    await capture(page, "desktop-longue-traine");
  });

  test("Découverte et Analyse restent sans jargon anglais public", async ({
    page,
  }) => {
    await page.setViewportSize({ height: 900, width: 1440 });
    const publicRoutes = [
      "/robin-live",
      "/matchs",
      "/observatoire",
      "/resultats",
      "/methode",
      "/hypotheses",
      "/hypotheses/familles",
      "/hypotheses/arbres",
      "/hypotheses/classements",
      "/hypotheses/observations",
      "/hypotheses/longue-traine",
    ];

    for (const route of publicRoutes) {
      await openPage(page, route);
      await expect(
        page.getByRole("button", { name: /^Vue Découverte\./ }),
      ).toHaveAttribute("aria-pressed", "true");
      await assertFrenchVocabulary(page);
    }

    await page.getByRole("button", { name: /^Vue Analyse\./ }).click();
    for (const route of publicRoutes) {
      await openPage(page, route);
      await expect(
        page.getByRole("button", { name: /^Vue Analyse\./ }),
      ).toHaveAttribute("aria-pressed", "true");
      await assertFrenchVocabulary(page);
    }

    // La Vue Expert est volontairement hors du contrôle lexical public.
    // Les valeurs techniques restent en outre confinées aux éléments code/pre.
    await openPage(page, "/hypotheses/J10-M001");
    await page.getByRole("button", { name: /^Vue Expert\./ }).click();
    await expect(page.locator("code").first()).toBeVisible();
  });
});
