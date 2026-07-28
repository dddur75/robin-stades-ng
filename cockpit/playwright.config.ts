import { defineConfig } from "@playwright/test";

export default defineConfig({
  expect: {
    timeout: 5_000,
  },
  forbidOnly: Boolean(process.env.CI),
  fullyParallel: false,
  outputDir: ".ci/visual-regression/test-results",
  reporter: [["list"], ["html", { open: "never", outputFolder: ".ci/visual-regression/report" }]],
  retries: process.env.CI ? 1 : 0,
  testDir: "./tests",
  testMatch: "visual-regression.spec.ts",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    colorScheme: "light",
    locale: "fr-FR",
    reducedMotion: "reduce",
    timezoneId: "Europe/Paris",
  },
  webServer: {
    command: "pnpm exec vinext dev -p 4173 -H 127.0.0.1",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: "http://127.0.0.1:4173/robin-live",
  },
});
