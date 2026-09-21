/* Capture competition-demo function pages. Synthetic cases only provide UI state. */
const { chromium } = require("../frontend/node_modules/@playwright/test");
const fs = require("node:fs/promises");
const path = require("node:path");

const baseURL = process.env.LEX_SCREENSHOT_URL || "http://127.0.0.1:48785";
const password = process.env.LEX_SCREENSHOT_PASSWORD || "CompetitionFunctionScreenshots-Local";
const output = process.env.LEX_SCREENSHOT_DIR || path.resolve("deliverables", "系统截图", "功能页面");
const manifest = [];

async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 1600, height: 1050 },
    deviceScaleFactor: 1,
    locale: "zh-CN",
    colorScheme: "light",
  });
  const page = await context.newPage();

  async function shot(file, title, state) {
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.evaluate(() => window.scrollTo(0, 0));
    const target = path.join(output, file);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await page.screenshot({ path: target, fullPage: true });
    manifest.push({ file, title, state, url: page.url() });
  }

  async function dismissToast() {
    const close = page.getByRole("button", { name: "关闭提示" });
    if (await close.count()) await close.click().catch(() => {});
  }

  async function signIn(username, userPassword) {
    await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" })).catch(() => {});
    await page.goto("/");
    await page.getByLabel("用户名").fill(username);
    await page.getByLabel("本地访问口令").fill(userPassword);
    await page.getByRole("button", { name: "进入工作台" }).click();
    await page.getByRole("heading", { name: "案件工作台" }).waitFor();
  }

  async function createUser(username, role, userPassword) {
    const response = await page.evaluate(async ({ username, role, userPassword }) => {
      const result = await fetch("/api/v1/users", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, display_name: username, role, password: userPassword }),
      });
      return { status: result.status, body: await result.text() };
    }, { username, role, userPassword });
    if (![200, 409].includes(response.status)) throw new Error(response.body);
  }

  async function createScenario(scenario) {
    return page.evaluate(async (name) => {
      const response = await fetch("/api/v1/demos", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: name }),
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }, scenario);
  }

  async function openCase(caseData) {
    await page.getByRole("button", { name: "案件工作台" }).click();
    const row = page.locator(".case-row").filter({ hasText: caseData.id });
    await row.waitFor({ state: "visible" });
    await row.click();
    await page.getByRole("heading", { name: "事实与证据" }).waitFor();
  }

  async function createAndEvaluate(caseData) {
    await openCase(caseData);
    await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
    await page.getByRole("heading", { name: "逐项披露方案" }).waitFor();
    await dismissToast();
    await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.locator(".risk-banner").waitFor({ state: "visible" });
    await dismissToast();
  }

  async function fillLegalReview(conclusion) {
    await page.getByRole("radio", {
      name: conclusion === "reject" ? "否决本次请求" : "允许处理（不授予发送权）",
      exact: true,
    }).check();
    await page.locator(".legal-review fieldset.review-evidence-options").last().locator("input[type=checkbox]").first().check();
    await page.getByLabel("审批理由").fill(conclusion === "reject"
      ? "当前组合信息仍可能关联特定主体，人工复核否决本次请求。"
      : "已核对当前合成材料、处理目的与最小披露范围，允许继续本次演示流程。");
    await page.getByLabel("事实前提").fill("判断仅基于当前版本的合成材料与已冻结请求。");
    await page.getByLabel("权限判断").fill("人工复核结论不等同于发送授权，仍需独立审批。");
    await page.getByLabel("外部处理条件").fill("比赛版采用本地离线模拟，不调用真实外部服务。");
    await page.getByLabel("最小化措施").fill("仅保留生成摘要所必需的事实，身份已一致替换。");
    await page.getByLabel("最终依据").fill("依据当前材料、风险提示和选定法源作出本次判断。");
    const condition = page.locator(".legal-review .check-grid input[type=checkbox]").first();
    if (!(await condition.isChecked())) await condition.check();
    const source = page.getByLabel("法源", { exact: true });
    if (!(await source.inputValue())) await source.selectOption({ index: 0 });
    await page.locator(".legal-review .confirm-line input[type=checkbox]").check();
    await page.getByRole("button", {
      name: conclusion === "reject" ? "提交否决并阻断本次请求" : "提交法律复核结论",
    }).click();
  }

  try {
    await page.goto("/");
    await page.getByLabel("用户名").waitFor();
    await shot("00-公共功能页面/00-登录功能页.png", "登录", "本地账号与访问口令入口");

    await signIn("admin", password);
    await shot("00-公共功能页面/01-案件工作台功能页.png", "案件工作台", "空白工作台、功能阶段与演示入口");

    await createUser("function.legal", "legal_reviewer", "Function-Legal-123");
    await createUser("function.approver", "approver", "Function-Approver-123");
    const success = await createScenario("success");
    const veto = await createScenario("human_veto");
    const linkage = await createScenario("linkage");
    const stop = await createScenario("stop");
    await page.reload();
    await page.getByRole("heading", { name: "案件工作台" }).waitFor();

    await openCase(success);
    await shot("01-完整披露流程/02-材料与事实功能页.png", "材料与事实", "原文、事实抽取、身份映射与依据留痕");
    await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
    await page.getByRole("heading", { name: "逐项披露方案" }).waitFor();
    await dismissToast();
    await shot("01-完整披露流程/03-披露方案功能页.png", "披露方案", "逐字段保留、替换、删除与请求预览");
    await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.locator(".risk-banner").waitFor();

    await createAndEvaluate(linkage);
    await shot("03-组合线索风险/04-第一层次-边侧风险门禁功能页.png", "边侧风险门禁", "边侧模型判定不可外发并阻断");

    await createAndEvaluate(veto);
    await shot("02-人工复核否决/05-人工复核功能页.png", "人工复核门禁", "边侧初检后等待具名人工复核");
    await signIn("function.legal", "Function-Legal-123");
    await openCase(veto);
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.getByLabel("审批理由").waitFor();
    await fillLegalReview("reject");
    await page.getByRole("heading", { name: "人工复核已否决，本次请求不可继续" }).waitFor();
    await shot("02-人工复核否决/06-第二层次-人工复核否决功能页.png", "人工复核门禁", "模型初检允许、人工复核否决并关闭后续入口");

    await openCase(success);
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.getByLabel("审批理由").waitFor();
    await fillLegalReview("allow");
    await page.getByText("人工复核：已完成", { exact: true }).waitFor();
    await shot("01-完整披露流程/07-第三层次-模型与人工均允许功能页.png", "双重门禁通过", "模型与人工复核均允许，等待独立审批");

    await signIn("function.approver", "Function-Approver-123");
    await openCase(success);
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.getByRole("button", { name: "审批当前完整请求" }).click();
    await page.getByRole("button", { name: "已知悉并批准当前版本" }).click();

    await signIn("admin", password);
    await openCase(success);
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.getByRole("button", { name: "执行任务" }).click();
    await page.getByRole("button", { name: "查看摘要与回链" }).waitFor();

    await signIn("function.legal", "Function-Legal-123");
    await openCase(success);
    await page.getByRole("button", { name: /03 风险与审批/ }).click();
    await page.getByRole("button", { name: "查看摘要与回链" }).click();
    await page.getByText("本地预置结果").waitFor();
    const reviews = page.getByRole("button", { name: "已核对本项", exact: true });
    while (await reviews.count()) {
      await reviews.first().click();
      await page.locator(".busy-bar").waitFor({ state: "detached" }).catch(() => {});
    }
    await page.getByRole("button", { name: "确认最终结果", exact: true }).click();
    await page.getByRole("button", { name: "结果已确认", exact: true }).waitFor();
    await shot("01-完整披露流程/08-摘要与来源回链功能页.png", "摘要与来源回链", "审批后离线执行、逐项核对与来源回链");

    await signIn("admin", password);
    await createAndEvaluate(stop);
    await page.getByRole("button", { name: "停止任务", exact: true }).click();
    await page.getByRole("heading", { name: /任务已主动停止，本次请求不可继续/ }).waitFor();
    await shot("04-主动停止/09-主动停止功能页.png", "主动停止", "材料不足时终止当前请求并保留留痕");

    const pages = [
      ["法学规则中心", "法学规则中心", "00-公共功能页面/10-法学规则中心功能页.png", "规则、任务与人工复核边界"],
      ["法学证据登记", "法学证据登记", "00-公共功能页面/11-法学证据登记功能页.png", "法学证据登记与状态"],
      ["服务商治理", "服务商治理", "00-公共功能页面/12-服务商治理功能页.png", "服务商档案与治理状态"],
      ["隔离实验", "隔离研究与风险攻击", "00-公共功能页面/13-隔离实验功能页.png", "隔离研究能力状态"],
      ["运行配置", "运行配置", "00-公共功能页面/14-运行配置功能页.png", "端侧模型与云端目标配置"],
      ["本地用户", "本地用户与角色", "00-公共功能页面/15-本地用户与角色功能页.png", "本地账号和角色管理"],
    ];
    for (const [nav, heading, file, state] of pages) {
      await page.getByRole("button", { name: nav, exact: true }).click();
      await page.getByRole("heading", { name: heading, exact: true }).waitFor();
      await shot(file, heading, state);
    }

    manifest.sort((left, right) => left.file.localeCompare(right.file, "zh-CN"));
    await fs.writeFile(path.join(output, "功能页面截图清单.json"), JSON.stringify({
      generated_at: new Date().toISOString(),
      base_url: baseURL,
      viewport: "1600x1050",
      screenshots: manifest,
    }, null, 2) + "\n", "utf8");
    await fs.writeFile(path.join(output, "功能页面截图说明.md"),
      "# 比赛版演示系统功能页面截图\n\n" +
      "截图主体是系统功能页面；后台合成数据仅用于呈现功能状态，不作为案例材料交付。\n\n" +
      "## 四个功能边界\n\n" +
      "1. `01-完整披露流程/`：模型与人工复核均允许，进入独立审批和摘要回链。\n" +
      "2. `02-人工复核否决/`：模型初检允许，人工复核不允许。\n" +
      "3. `03-组合线索风险/`：边侧模型判定不可外发。\n" +
      "4. `04-主动停止/`：材料不足或条件不满足时主动终止。\n\n" +
      "> 比赛版使用完全合成数据。第三层以本地预置结果模拟后续处理，不表示生产环境已允许正式发送。\n\n" +
      "## 页面清单\n\n" + manifest.map(item => `- \`${item.file}\`：${item.title} · ${item.state}`).join("\n") + "\n",
      "utf8");
    console.log(JSON.stringify({ output, count: manifest.length }, null, 2));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
