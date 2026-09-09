/**
 * 本机视觉 walker，不进 CI。
 * 默认 http://127.0.0.1:18765；口令与 Playwright 相同（local-acceptance-only）。
 * 截图写入仓库根下 .data/ui-walk/。运行：pnpm walk:ui
 */
import { chromium } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const shots = path.join(frontend, "../.data/ui-walk");
const baseURL = "http://127.0.0.1:18765";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const seen = [];

async function shot(name) {
  await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
  seen.push(name);
}

await page.goto(baseURL + "/");
await page.getByLabel("本地访问口令").fill("local-acceptance-only");
await page.getByRole("button", { name: "进入工作台" }).click();
await page.getByRole("heading", { name: "案件工作台" }).waitFor();
if (!(await page.getByText("按目的披露").isVisible())) throw new Error("dashboard eyebrow missing");
if (!(await page.getByRole("button", { name: /01 完整披露流程/ }).isVisible())) throw new Error("demo 01 missing");
await shot("01-dashboard");

await page.getByRole("button", { name: /01 完整披露流程/ }).click();
await page.getByRole("heading", { name: "事实与证据" }).waitFor();
await shot("02-facts");
await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
await page.getByRole("heading", { name: "逐项披露方案" }).waitFor();
await shot("03-disclosure");
await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
await page.getByRole("heading", { name: "当前门禁允许进入审批" }).waitFor();
await shot("04-risk");
await page.getByRole("button", { name: "审批当前完整请求" }).click();
await page.getByRole("button", { name: "已知悉并批准当前版本" }).click();
await page.getByRole("button", { name: "执行模拟调用" }).click();
await page.getByRole("button", { name: "查看摘要与回链" }).click();
await page.getByText("模拟结果 · 非模型生成").waitFor();
await shot("05-result");

await page.getByRole("button", { name: "返回案件列表" }).click();
await page.getByRole("button", { name: "新建案件", exact: true }).click();
await page.getByLabel("案件名称").fill("视觉验收 · 正式材料");
await page.getByRole("button", { name: "创建正式案件" }).click();
await page.locator("input[type=file]").setInputFiles(path.resolve(frontend, "../examples/synthetic_labor.docx"));
await page.locator(".source-text").waitFor();
await page.getByRole("button", { name: "添加事实" }).click();
await page.getByLabel("事实内容").fill("纯合成劳动争议材料");
await page.getByLabel("我已核对事实及其来源").check();
await page.getByRole("button", { name: "保存事实", exact: true }).click();
await page.locator(".fact-card").waitFor();
await page.locator(".busy-bar").waitFor({ state: "detached" }).catch(() => {});
await page.getByRole("button", { name: "云端摘要任务", exact: true }).click();
await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
await page.getByText("适用规则尚未正式发布").waitFor();
const falsePass = await page.getByText("已通过", { exact: true }).count();
if (falsePass) throw new Error("false pass status appeared");
await shot("06-formal-block");

await page.getByRole("button", { name: "运行配置", exact: true }).click();
await page.getByText("未运行、错误和不确定均不算通过").waitFor({ timeout: 15000 });
await shot("07-settings");

await page.getByRole("button", { name: "切换深色主题" }).click();
await page.waitForTimeout(200);
await shot("08-settings-dark");

await page.setViewportSize({ width: 390, height: 844 });
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
if (overflow) throw new Error("horizontal overflow at 390");
await shot("09-mobile-390");

await browser.close();
console.log("ui-walk ok", seen.join(", "));
