import { expect, test, type Locator, type Page } from "@playwright/test";

type ViewMode = "analysis" | "discovery" | "expert";

type ReconciledHypothesis = Readonly<{
  averageOdds: string;
  competition: string;
  drawdown: string;
  folds: string;
  groups: string;
  hitRate: string;
  id: "J10-M001" | "J10-M002" | "J10-M003";
  losses: number;
  occurrences: number;
  profit: string;
  roi: string;
  selection: RegExp;
  wins: number;
}>;

const outputRoot = ".ci/visual-regression/captures";
const historicalMatchId = "api-football:608482";
const historicalMatchTitle = "Genoa – Crotone";
const m002MatchListPath = "/hypotheses/J10-M002/matchs";
const historicalMatchPath =
  "/matchs/historique/api-football%3A608482" +
  "?hypothese=J10-M002&retour=%2Fhypotheses%2FJ10-M002%2Fmatchs";

const topThree: readonly ReconciledHypothesis[] = [
  {
    averageOdds: "2,25",
    competition: "La Liga",
    drawdown: "9,27 u",
    folds: "4/4",
    groups: "225",
    hitRate: "51,72 %",
    id: "J10-M001",
    losses: 126,
    occurrences: 261,
    profit: "+43,43 u",
    roi: "+16,64 %",
    selection: /victoire à l’extérieur/iu,
    wins: 135,
  },
  {
    averageOdds: "3,09",
    competition: "Serie A",
    drawdown: "19,52 u",
    folds: "4/4",
    groups: "282",
    hitRate: "37,47 %",
    id: "J10-M002",
    losses: 227,
    occurrences: 363,
    profit: "+57,88 u",
    roi: "+15,94 %",
    selection: /match nul/iu,
    wins: 136,
  },
  {
    averageOdds: "1,78",
    competition: "Serie A",
    drawdown: "7,22 u",
    folds: "3/3",
    groups: "207",
    hitRate: "63,90 %",
    id: "J10-M003",
    losses: 87,
    occurrences: 241,
    profit: "+33,42 u",
    roi: "+13,87 %",
    selection: /victoire à l’extérieur/iu,
    wins: 154,
  },
] as const;

async function useMode(page: Page, mode: ViewMode) {
  await page.addInitScript((selectedMode) => {
    window.localStorage.setItem(
      "robin-experience-view-mode",
      selectedMode,
    );
  }, mode);
}

async function openPage(
  page: Page,
  path: string,
  heading?: string | RegExp,
) {
  const response = await page.goto(path);
  expect(response?.ok(), `${path} doit répondre avec succès`).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  await expect(
    page.locator('html[data-robin-hydrated="true"]'),
  ).toBeVisible();
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
        if (root.scrollWidth <= root.clientWidth) return "BOUNDED";
        const offenders = [
          ...document.querySelectorAll<HTMLElement>("body *"),
        ]
          .map((element) => {
            const bounds = element.getBoundingClientRect();
            return {
              className: element.className,
              left: Math.round(bounds.left),
              right: Math.round(bounds.right),
              tag: element.tagName,
              width: Math.round(bounds.width),
            };
          })
          .filter(
            (item) =>
              item.left < 0 || item.right > root.clientWidth,
          )
          .slice(0, 8);
        return JSON.stringify({
          clientWidth: root.clientWidth,
          offenders,
          scrollWidth: root.scrollWidth,
        });
      }),
    )
    .toBe("BOUNDED");
}

async function capture(
  page: Page,
  name: string,
  target?: Locator,
) {
  if (target) {
    await target.screenshot({
      animations: "disabled",
      path: `${outputRoot}/${name}.png`,
    });
    return;
  }
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    window.scrollTo(0, 0);
  });
  await page.waitForFunction(
    () => window.scrollX === 0 && window.scrollY === 0,
  );
  await page.screenshot({
    animations: "disabled",
    fullPage: true,
    path: `${outputRoot}/${name}.png`,
  });
}

function definitionValue(scope: Locator | Page, label: string) {
  return scope
    .locator("dt")
    .filter({ hasText: label })
    .first()
    .locator("xpath=following-sibling::dd");
}

function rankingCard(page: Page, hypothesisId: string) {
  return page
    .locator("article.hu-evidence-ranking-card")
    .filter({ hasText: hypothesisId });
}

async function assertRoiIsNotHitRate(
  scope: Locator | Page,
  evidence: ReconciledHypothesis,
) {
  const hitRate = definitionValue(scope, "Taux de réussite");
  const historicalRoi = definitionValue(
    scope,
    "ROI historique brut",
  );
  await expect(hitRate).toHaveText(evidence.hitRate);
  await expect(hitRate).not.toContainText(evidence.roi);
  await expect(historicalRoi).toHaveText(evidence.roi);
  await expect(historicalRoi).not.toContainText(evidence.hitRate);
}

async function assertRankingCard(
  page: Page,
  evidence: ReconciledHypothesis,
) {
  const card = rankingCard(page, evidence.id);
  await expect(card).toBeVisible();
  await expect(card).toContainText(evidence.competition);
  await expect(
    definitionValue(card, "Occurrences historiques"),
  ).toHaveText(String(evidence.occurrences));
  await expect(definitionValue(card, "Profit simulé")).toHaveText(
    evidence.profit,
  );
  await expect(
    definitionValue(card, "Gagnés / perdus / annulés"),
  ).toHaveText(`${evidence.wins} / ${evidence.losses} / 0`);
  await expect(definitionValue(card, "Cote moyenne")).toHaveText(
    evidence.averageOdds,
  );
  await expect(
    definitionValue(card, "Périodes positives"),
  ).toHaveText(evidence.folds);
  await expect(
    definitionValue(card, "Baisse maximale"),
  ).toHaveText(evidence.drawdown);
  await assertRoiIsNotHitRate(card, evidence);
}

async function assertHypothesisDetail(
  page: Page,
  evidence: ReconciledHypothesis,
) {
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: evidence.selection,
    }),
  ).toBeVisible();
  await expect(page.getByText(evidence.id, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(evidence.competition, { exact: true }).first()).toBeVisible();
  await expect(
    definitionValue(page, "Occurrences historiques"),
  ).toHaveText(String(evidence.occurrences));
  await expect(definitionValue(page, "Profit simulé")).toHaveText(
    evidence.profit,
  );
  await expect(
    definitionValue(page, "Gagnés / perdus / annulés"),
  ).toHaveText(`${evidence.wins} / ${evidence.losses} / 0`);
  await expect(definitionValue(page, "Cote moyenne")).toHaveText(
    evidence.averageOdds,
  );
  await expect(definitionValue(page, "Baisse maximale")).toHaveText(
    evidence.drawdown,
  );
  await expect(
    definitionValue(page, "Validation chronologique glissante"),
  ).toContainText(`${evidence.folds} périodes positives`);
  await expect(
    definitionValue(page, "Groupes statistiques distincts"),
  ).toHaveText(evidence.groups);
  await expect(
    definitionValue(
      page,
      "Risque de faux positif après correction",
    ),
  ).toHaveText("1,00");
  await assertRoiIsNotHitRate(page, evidence);
}

async function waitForHistoricalCharts(page: Page) {
  await expect(
    page.getByRole("heading", {
      name: "Évolution du profit historique cumulé",
    }),
  ).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByRole("heading", {
      name: "Résultat historique par saison",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Ventilations historiques indisponibles",
    }),
  ).toHaveCount(0);
}

test.describe("Univers des hypothèses V1.2 — preuves auditables", () => {
  test.describe.configure({ mode: "serial" });

  test("classements global, Liga et Serie A avec statistiques réconciliées", async ({
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
      page.getByRole("button", { exact: true, name: "Global" }),
    ).toHaveAttribute("aria-pressed", "true");
    for (const evidence of topThree) {
      await assertRankingCard(page, evidence);
    }
    await assertNoDocumentOverflow(page);
    await capture(page, "desktop-classement-global-avec-stats");

    await openPage(
      page,
      "/hypotheses/classements?competition=Liga",
      "Classements des hypothèses",
    );
    await expect(
      page.getByRole("button", { exact: true, name: "Liga" }),
    ).toHaveAttribute("aria-pressed", "true");
    await assertRankingCard(page, topThree[0]);
    await expect(page.getByText("+16,64 %", { exact: true }).first()).toBeVisible();
    await capture(page, "desktop-classement-liga-avec-16-64-roi");

    await openPage(
      page,
      "/hypotheses/classements?competition=Serie%20A",
      "Classements des hypothèses",
    );
    await expect(
      page.getByRole("button", { exact: true, name: "Serie A" }),
    ).toHaveAttribute("aria-pressed", "true");
    await assertRankingCard(page, topThree[1]);
    await assertRankingCard(page, topThree[2]);
    await capture(page, "desktop-classement-serie-a");
  });

  test("fiches J10-M001, J10-M002 et J10-M003 sans confusion ROI/réussite", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });

    await openPage(page, "/hypotheses/J10-M001");
    await assertHypothesisDetail(page, topThree[0]);
    await waitForHistoricalCharts(page);
    await capture(page, "desktop-j10-m001-complete");

    await openPage(page, "/hypotheses/J10-M002");
    await assertHypothesisDetail(page, topThree[1]);
    await waitForHistoricalCharts(page);
    await expect(
      page.getByText("entre 2,50 et 3,25", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("inférieure ou égale à 6,00 %", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByText("Intervalle observé : +0,43 % à +31,39 %.", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.locator(`a[href="${m002MatchListPath}"]`).first(),
    ).toBeVisible();
    await capture(page, "desktop-j10-m002-complete");

    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await capture(page, "mobile-j10-m002-complete");

    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M003");
    await assertHypothesisDetail(page, topThree[2]);
  });

  test("parcours fiche, liste, match historique et retour contextuel", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });

    await openPage(page, "/hypotheses/J10-M002");
    const matchListLink = page
      .locator(`a[href="${m002MatchListPath}"]`)
      .first();
    await expect(matchListLink).toBeVisible();
    await matchListLink.click();
    await expect(page).toHaveURL(new RegExp(`${m002MatchListPath}$`));
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Matchs de J10-M002",
      }),
    ).toBeVisible();
    await expect(
      page.getByText("363 occurrences historiques"),
    ).toBeVisible();
    await expect(
      page.getByRole("region", {
        name: "Tableau des matchs historiques",
      }),
    ).toBeVisible();
    await expect(page.getByText(historicalMatchTitle).first()).toBeVisible();
    const firstHistoricalMatch = page
      .locator(
        `a[href*="/matchs/historique/${encodeURIComponent(historicalMatchId)}"]`,
      )
      .first();
    await expect(firstHistoricalMatch).toBeVisible();
    await expect(firstHistoricalMatch).toHaveAttribute(
      "href",
      historicalMatchPath,
    );
    await capture(page, "desktop-j10-m002-match-list");

    await firstHistoricalMatch.click();
    await expect(page).toHaveURL(/\/matchs\/historique\/api-football%3A608482/iu);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: historicalMatchTitle,
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Score final 4 – 1"),
    ).toBeVisible();
    await expect(
      page.getByText(
        /70 règles historiques réconciliées\s*;\s*aperçu borné de\s+\d+\s+relation(?:s)? navigable(?:s)?/iu,
      ),
    ).toBeVisible();
    await expect(
      definitionValue(page, "Sélection"),
    ).toHaveText("Match nul");
    await expect(
      definitionValue(page, "Cote observée"),
    ).toHaveText("3,23");
    await expect(
      definitionValue(page, "Profit simulé"),
    ).toHaveText("-1,00 unité");
    await expect(
      page.getByRole("link", { name: "Ouvrir la fiche hypothèse" }),
    ).toHaveAttribute("href", "/hypotheses/J10-M002");
    await expect(
      page.getByRole("link", {
        name: "Retour à la liste contextuelle",
      }),
    ).toHaveAttribute("href", m002MatchListPath);
    await capture(page, "desktop-historical-match-detail");

    await page
      .getByRole("link", { name: "Retour à la liste contextuelle" })
      .click();
    await expect(page).toHaveURL(new RegExp(`${m002MatchListPath}$`));

    await page.setViewportSize({ height: 844, width: 390 });
    await assertNoDocumentOverflow(page);
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Matchs de J10-M002",
      }),
    ).toBeVisible();
    await capture(page, "mobile-j10-m002-match-list");
  });

  test("bankroll et saisons utilisent les 363 matchs reconstruits", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M002");
    await waitForHistoricalCharts(page);

    const bankroll = page
      .getByRole("heading", {
        name: "Évolution du profit historique cumulé",
      })
      .locator("xpath=ancestor::figure[1]");
    await expect(bankroll.getByRole("img")).toHaveAttribute(
      "aria-label",
      /part explicitement de 0 u.*363 matchs/iu,
    );
    const bankrollMatchLinks = bankroll.locator(
      `a[href*="/matchs/historique/${encodeURIComponent(historicalMatchId)}"]`,
    );
    await expect
      .poll(() => bankrollMatchLinks.count())
      .toBeGreaterThan(0);
    await expect(bankrollMatchLinks.first()).toHaveAttribute(
      "href",
      /hypothese=J10-M002/iu,
    );
    await capture(page, "desktop-bankroll-chart", bankroll);

    const seasons = page
      .getByRole("heading", {
        name: "Résultat historique par saison",
      })
      .locator("xpath=ancestor::figure[1]");
    await expect(seasons).toContainText(
      /363 observations sont réparties sur 6 saisons/iu,
    );
    await capture(page, "desktop-season-breakdown", seasons);
  });

  test("longue traîne publique sans diagnostic de valeur manquante", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(
      page,
      "/hypotheses/longue-traine",
      "La longue traîne",
    );
    const publicText = await page.getByRole("main").innerText();
    expect(publicText).not.toMatch(/\bvaleurs?\s+manquantes?\b/iu);
    await expect(
      page.locator(
        '[data-semantic-role="DATA_QUALITY_METADATA"], [data-semantic-role="AVAILABILITY_METADATA"], [data-semantic-role="PROVENANCE_METADATA"]',
      ),
    ).toHaveCount(0);
    await capture(page, "desktop-long-tail-without-missing-values");
  });

  test("qualité des données séparée dans l’espace Expert", async ({
    page,
  }) => {
    await useMode(page, "expert");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(
      page,
      "/expert/qualite-donnees",
      "Qualité et disponibilité des données",
    );
    await expect(
      page.getByRole("heading", {
        name: "Valeurs manquantes et disponibilité",
      }),
    ).toBeVisible();
    await expect(
      page.getByText(
        /Elles ne constituent jamais une hypothèse football publique/iu,
      ),
    ).toBeVisible();
    await capture(page, "desktop-data-quality-missingness");
  });

  test("onglet prospectif vide, clavier et séparation des phases", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M002");

    const historicalTab = page.getByRole("tab", {
      name: "Simulation historique",
    });
    const prospectiveTab = page.getByRole("tab", {
      name: "Observation depuis le gel",
    });
    await historicalTab.focus();
    await historicalTab.press("ArrowRight");
    await expect(prospectiveTab).toBeFocused();
    await expect(prospectiveTab).toHaveAttribute(
      "aria-selected",
      "true",
    );
    const prospectivePanel = page.getByRole("tabpanel", {
      name: "Observation depuis le gel",
    });
    await expect(
      prospectivePanel.getByRole("heading", {
        name: "Aucune preuve prospective dans ce rapport",
      }),
    ).toBeVisible();
    await expect(prospectivePanel).toContainText(
      "Cette fiche lit exclusivement la preuve historique Jalon 10.",
    );
    await expect(prospectivePanel).toContainText(
      "363 résultats historiques réglés",
    );
    await capture(page, "desktop-no-prospective-observation");
  });

  test("zoom texte 200 % et parcours clavier restent utilisables", async ({
    page,
  }) => {
    await useMode(page, "analysis");
    await page.setViewportSize({ height: 900, width: 1440 });
    await openPage(page, "/hypotheses/J10-M002");

    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", {
      name: "Aller au contenu principal",
    });
    await expect(skipLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();

    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await expect(page.getByRole("main")).toBeVisible();
    await assertNoDocumentOverflow(page);
    await capture(page, "zoom-200-hypothesis-detail");
  });
});
