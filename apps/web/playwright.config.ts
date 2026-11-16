import { defineConfig } from "@playwright/test";

/**
 * Parcours de bout en bout sur le build de production, contre l'API locale réelle
 * (make api-run) et Martin (make up). Chrome système ; WebGL logiciel pour la carte.
 */
const PORT = Number(process.env.WEB_PORT ?? 3123);

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: "chrome",
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "bureau", use: { viewport: { width: 1440, height: 900 } } },
    { name: "telephone", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: `npx next start --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
