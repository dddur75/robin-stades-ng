import { defineConfig } from "@playwright/test";

const nodeExecutable = JSON.stringify(process.execPath);
const webServerCommand =
  process.platform === "win32"
    ? `${nodeExecutable} node_modules/vinext/dist/cli.js dev -p 4173 -H 127.0.0.1`
    : `${nodeExecutable} node_modules/vinext/dist/cli.js start -p 4173 -H 127.0.0.1`;
const usesExternalServer = process.env.PLAYWRIGHT_EXTERNAL_SERVER === "1";

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
  testMatch: [
    "visual-regression.spec.ts",
    "hypothesis-universe.spec.ts",
    "hypothesis-accessibility.spec.ts",
  ],
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:4173",
    colorScheme: "light",
    locale: "fr-FR",
    reducedMotion: "reduce",
    timezoneId: "Europe/Paris",
  },
  webServer: usesExternalServer
    ? undefined
    : {
        command: webServerCommand,
        reuseExistingServer: false,
        timeout: 120_000,
        url: "http://127.0.0.1:4173/robin-live",
      },
});
