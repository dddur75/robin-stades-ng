import { expect, test, type Page } from "@playwright/test";

const route = "/expert/qualite-donnees";
const outputRoot = ".ci/visual-regression/captures";
const viewports = [
  { width: 360, height: 800 },
  { width: 375, height: 844 },
  { width: 390, height: 844 },
  { width: 430, height: 932 },
  { width: 768, height: 1024 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

async function assertNoDocumentOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const root = document.documentElement;
        if (root.scrollWidth <= root.clientWidth) return "BOUNDED";
        const offenders = [...document.querySelectorAll<HTMLElement>("body *")]
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
          .filter((item) => item.left < 0 || item.right > root.clientWidth)
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

async function openDesk(page: Page) {
  const response = await page.goto(route);
  expect(response?.ok()).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("lang", "fr-FR");
  await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  const desk = page.locator("#coverage-p0");
  await expect(desk).toBeVisible();
  await expect(
    desk.getByRole("heading", { level: 2, name: "Desk de couverture P0" }),
  ).toBeVisible();
  return desk;
}

test.describe("Desk de couverture P0 privé", () => {
  test("représente la preuve partielle sans inventer de performance", async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const externalRequests = new Set<string>();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
        externalRequests.add(url.origin);
      }
    });

    await page.setViewportSize({ height: 900, width: 1440 });
    const desk = await openDesk(page);
    await expect(desk.getByText("Définition E0 fermée", { exact: true })).toBeVisible();
    await expect(desk.getByText("Preuve empirique ouverte", { exact: true })).toBeVisible();
    await expect(desk.getByText("480", { exact: true })).toBeVisible();
    await expect(desk.getByText("0/17", { exact: true })).toBeVisible();
    await expect(desk.getByText("0/8", { exact: true })).toBeVisible();
    await expect(desk.getByText("UNKNOWN", { exact: true })).toHaveCount(3);
    await expect(desk.getByText("Non mesuré", { exact: true })).toHaveCount(19);
    await expect(desk.locator('[aria-disabled="true"]', { hasText: "Stratégie" })).toHaveCount(1);
    await expect(desk.locator('[aria-disabled="true"]', { hasText: "Matchs" })).toHaveCount(1);
    await expect(desk.getByRole("link", { name: "Données" })).toHaveAttribute(
      "href",
      "#coverage-p0-table",
    );
    await expect(desk.getByRole("link", { name: "Hypothèse" })).toHaveAttribute(
      "href",
      "#gates-calendar-fatigue",
    );
    const text = (await desk.innerText()).replace(/\s+/gu, " ");
    expect(text).not.toMatch(/\b(?:ROI|profit|drawdown|cote|classement|comparateur)\b/iu);
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect([...externalRequests]).toEqual([]);
  });

  test("reste borné et lisible de 360 à 1920 px", async ({ page }) => {
    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      const desk = await openDesk(page);
      await assertNoDocumentOverflow(page);
      await desk.screenshot({
        animations: "disabled",
        path: `${outputRoot}/p0-coverage-desk-${viewport.width}.png`,
      });
    }
  });

  test("conserve le parcours clavier, les ancres et le zoom texte 200 %", async ({ page }) => {
    await page.setViewportSize({ height: 932, width: 430 });
    const desk = await openDesk(page);

    const dataLink = desk.getByRole("link", { name: "Données" });
    await dataLink.focus();
    await expect(dataLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#coverage-p0-table$/u);
    await expect(page.locator("#coverage-p0-table")).toBeFocused();

    const hypothesisLink = desk.getByRole("link", { name: "Hypothèse" });
    await hypothesisLink.focus();
    await expect(hypothesisLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#gates-calendar-fatigue$/u);
    await expect(page.locator("#gates-calendar-fatigue")).toBeVisible();
    await expect
      .poll(() =>
        page.locator("#gates-calendar-fatigue").evaluate((element) =>
          Math.round(element.getBoundingClientRect().top),
        ),
      )
      .toBeGreaterThanOrEqual(90);

    await page.setViewportSize({ height: 900, width: 1440 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    await assertNoDocumentOverflow(page);
    await expect(desk.getByRole("heading", { name: "Desk de couverture P0" })).toBeVisible();
    await desk.screenshot({
      animations: "disabled",
      path: `${outputRoot}/p0-coverage-desk-1440-text-zoom-200.png`,
    });
  });
});
