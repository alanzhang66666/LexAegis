import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const executablePath = process.env.LEX_CHROME || (process.platform === "darwin" && existsSync(macChrome) ? macChrome : undefined);
export default defineConfig({
  testDir: "./e2e", testMatch: "gate-bundle.spec.ts", workers: 1, timeout: 20000,
  use: {baseURL:"http://127.0.0.1:4179", launchOptions:{executablePath}},
  webServer: {command:"./node_modules/.bin/vite --host 127.0.0.1 --port 4179 --strictPort",url:"http://127.0.0.1:4179/test-fixtures/gate-view.html",reuseExistingServer:false,timeout:30000},
  reporter:"list", outputDir:"test-results/v3-gate",
});
