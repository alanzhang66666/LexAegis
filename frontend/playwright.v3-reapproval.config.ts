import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const executablePath = process.env.LEX_CHROME || (process.platform === "darwin" && existsSync(macChrome) ? macChrome : undefined);
export default defineConfig({
  testDir:"./e2e",testMatch:"reapproval.spec.ts",workers:1,timeout:20000,
  use:{baseURL:"http://127.0.0.1:4180",launchOptions:{executablePath}},
  webServer:{command:"node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4180 --strictPort",url:"http://127.0.0.1:4180/test-fixtures/reapproval.html",reuseExistingServer:false,timeout:30000},
  reporter:"list",outputDir:"test-results/v3-reapproval",
});
