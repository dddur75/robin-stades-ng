import { expect, test } from "@playwright/test";

test.describe("Univers des hypothèses — accessibilité", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "robin-experience-view-mode",
        "discovery",
      );
    });
    await page.goto("/hypotheses");
    await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();
  });

  test("le glossaire piège le focus, se ferme avec Échap et rend le focus", async ({
    page,
  }) => {
    const trigger = page.getByRole("button", { name: "Glossaire" });
    await trigger.focus();
    await trigger.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Glossaire" });
    const close = dialog.getByRole("button", { name: "Fermer" });
    await expect(dialog).toBeVisible();
    await expect(close).toBeFocused();

    await page.keyboard.press("Shift+Tab");
    await expect(dialog.locator("summary").last()).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(close).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("les textes visibles respectent le contraste WCAG AA", async ({
    page,
  }) => {
    const failures = await page.evaluate(() => {
      const parseRgb = (value: string) => {
        const match = value.match(
          /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)/,
        );
        if (!match) return null;
        return {
          a: match[4] === undefined ? 1 : Number(match[4]),
          b: Number(match[3]),
          g: Number(match[2]),
          r: Number(match[1]),
        };
      };
      const composite = (
        foreground: { a: number; b: number; g: number; r: number },
        background: { a: number; b: number; g: number; r: number },
      ) => ({
        a: 1,
        b: foreground.b * foreground.a + background.b * (1 - foreground.a),
        g: foreground.g * foreground.a + background.g * (1 - foreground.a),
        r: foreground.r * foreground.a + background.r * (1 - foreground.a),
      });
      const luminance = (color: { b: number; g: number; r: number }) => {
        const channel = (value: number) => {
          const normalized = value / 255;
          return normalized <= 0.04045
            ? normalized / 12.92
            : ((normalized + 0.055) / 1.055) ** 2.4;
        };
        return (
          0.2126 * channel(color.r) +
          0.7152 * channel(color.g) +
          0.0722 * channel(color.b)
        );
      };
      const ratio = (
        foreground: { b: number; g: number; r: number },
        background: { b: number; g: number; r: number },
      ) => {
        const lighter = Math.max(
          luminance(foreground),
          luminance(background),
        );
        const darker = Math.min(
          luminance(foreground),
          luminance(background),
        );
        return (lighter + 0.05) / (darker + 0.05);
      };
      const backgroundFor = (element: HTMLElement) => {
        let current: HTMLElement | null = element;
        const layers: Array<{ a: number; b: number; g: number; r: number }> =
          [];
        while (current) {
          const style = getComputedStyle(current);
          if (style.backgroundImage !== "none") return null;
          const parsed = parseRgb(style.backgroundColor);
          if (parsed?.a === 1) {
            let result = parsed;
            for (const layer of layers.reverse()) {
              result = composite(layer, result);
            }
            return result;
          }
          if (parsed && parsed.a > 0) layers.push(parsed);
          current = current.parentElement;
        }
        return null;
      };

      return [...document.querySelectorAll<HTMLElement>("body *")]
        .filter((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          const ownsText = [...element.childNodes].some(
            (node) =>
              node.nodeType === Node.TEXT_NODE &&
              Boolean(node.textContent?.trim()),
          );
          return (
            ownsText &&
            !element.closest('[aria-hidden="true"]') &&
            rect.width > 0 &&
            rect.height > 0 &&
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            Number(style.opacity) > 0
          );
        })
        .flatMap((element) => {
          const style = getComputedStyle(element);
          const foreground = parseRgb(style.color);
          if (!foreground) return [];
          const background = backgroundFor(element);
          if (!background || !element.innerText.trim()) return [];
          const measured = ratio(
            composite(foreground, background),
            background,
          );
          const fontSize = Number.parseFloat(style.fontSize);
          const isBold = Number.parseInt(style.fontWeight, 10) >= 700;
          const threshold =
            fontSize >= 24 || (fontSize >= 18.66 && isBold) ? 3 : 4.5;
          if (measured + 0.01 >= threshold) return [];
          return [
            {
              contrast: Number(measured.toFixed(2)),
              selector:
                element.id ||
                element.className ||
                element.tagName.toLowerCase(),
              text: element.innerText.trim().slice(0, 80),
              threshold,
            },
          ];
        });
    });

    expect(failures).toEqual([]);
  });

  test("le mouvement réduit neutralise animations et transitions longues", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    await expect(page.locator('html[data-robin-hydrated="true"]')).toBeVisible();

    const offenders = await page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>("body *")]
        .filter((element) => {
          const style = getComputedStyle(element);
          const durations = [
            ...style.animationDuration.split(","),
            ...style.transitionDuration.split(","),
          ].map((value) =>
            value.trim().endsWith("ms")
              ? Number.parseFloat(value)
              : Number.parseFloat(value) * 1_000,
          );
          return durations.some((duration) => duration > 10);
        })
        .map((element) => element.className || element.tagName.toLowerCase()),
    );

    expect(offenders).toEqual([]);
  });
});
