import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e", testMatch: "registered-document.spec.ts", workers: 1, timeout: 90000,
  use: { baseURL: process.env.LEX_REGISTERED_E2E_URL, viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.LEX_CHROME } },
  reporter: "list", outputDir: "test-results/registered-document",
});
