import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { mkdir } from "node:fs/promises";

async function signIn(page: Page, username: string, password: string) {
  await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" }));
  await page.goto("/");
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("本地访问口令").fill(password);
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
}

async function saveAcceptanceScreenshot(page: Page, name: string) {
  const directory = path.resolve("../.artifacts/dual-track-acceptance");
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, name), fullPage: true });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("本地访问口令").fill("local-acceptance-only");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
});

test("human veto is visibly paused by a technical reviewer and rejected by legal", async ({ page }, testInfo) => {
  const accounts = [
    ["flow.operator", "operator-password-123", "case_operator"],
    ["flow.technical", "technical-password-123", "technical_reviewer"],
    ["flow.legal", "legal-review-password-123", "legal_reviewer"],
    ["flow.approver", "veto-approver-password-123", "approver"],
  ];
  for (const [username, password, role] of accounts) {
    const response = await page.evaluate(async ({ username, password, role }) => {
      const result = await fetch("/api/v1/users", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, display_name: username, role, password }) });
      return { status: result.status, body: await result.text() };
    }, { username, password, role });
    expect([200, 409]).toContain(response.status);
  }
  const login = async (username: string, password: string) => {
    await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" }));
    await page.goto("/");
    await page.getByLabel("用户名").fill(username);
    await page.getByLabel("本地访问口令").fill(password);
    await page.getByRole("button", { name: "进入工作台" }).click();
    await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  };

  await login("flow.operator", "operator-password-123");
  const created = page.waitForResponse(response => response.url().endsWith("/api/v1/demos") && response.request().method() === "POST");
  await page.getByRole("button", { name: /人工复核否决/ }).click();
  const caseResponse = await created;
  const caseData = await caseResponse.json();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(page.getByText("系统初检结果")).toBeVisible();

  await login("flow.technical", "technical-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await expect(page.getByText("系统初检结果")).toBeVisible();
  await page.getByLabel("技术复核问题说明").fill("岗位、园区与活动日期组合可关联到具体主体。");
  await page.locator(".technical-review .review-evidence-options input[type=checkbox]").first().check();
  await page.getByRole("button", { name: "暂停请求并提交技术问题" }).click();
  await expect(page.getByRole("heading", { name: "本次请求已暂停" })).toBeVisible();
  await expect(page.getByText("原初检结果保留供追溯，当前请求已停止。")).toBeVisible();

  await login("flow.legal", "legal-review-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByRole("radio", { name: "否决本次请求" }).check();
  await page.locator(".legal-review fieldset.review-evidence-options").last().locator("input[type=checkbox]").first().check();
  await page.getByLabel("审批理由").fill("补充合成线索与保留字段可以识别特定主体，本次请求不应发送。");
  await page.getByLabel("事实前提").fill("岗位、园区和活动日期仍在请求中。");
  await page.getByLabel("权限判断").fill("仅当前事项交由人工判断，不视为系统证明安全。");
  await page.getByLabel("外部处理条件").fill("本次请求的处理条件尚不充分。");
  await page.getByLabel("最小化措施").fill("移除非必要岗位、地点和活动日期后重新评估。");
  await page.getByLabel("最终依据").fill("结合当前材料版本和已选择的合成证据作出判断。");
  await page.locator(".legal-review .check-grid input[type=checkbox]").first().check();
  await page.getByLabel("法源", { exact: true }).selectOption({ index: 0 });
  await page.locator(".legal-review .confirm-line input[type=checkbox]").check();
  await page.getByRole("button", { name: "提交否决并阻断本次请求" }).click();
  await expect(page.getByRole("heading", { name: "人工复核已否决，本次请求不可继续" })).toBeVisible();
  await expect(page.getByText("否决仅针对当前请求；请调整后创建关联后继任务。")).toBeVisible();
  await expect(page.getByRole("button", { name: "审批当前完整请求" })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("human-veto-rejected.png"), fullPage: true });
  await saveAcceptanceScreenshot(page, "human-veto-rejected.png");
  const rejectedTaskId = await page.getByLabel("任务历史").inputValue();
  await login("flow.approver", "veto-approver-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByLabel("任务历史").selectOption(rejectedTaskId);
  await expect(page.getByRole("heading", { name: /人工复核已否决，本次请求不可继续/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "审批当前完整请求" })).toHaveCount(0);
  const approvalStatus = await page.evaluate(async ({ caseId, taskId }) => {
    const detail = await (await fetch(`/api/v1/cases/${caseId}`)).json();
    const task = detail.tasks.find((item:any) => item.id === taskId);
    return (await fetch(`/api/v1/tasks/${taskId}/approve`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_hash: task.request_hash }) })).status;
  }, { caseId: caseData.id, taskId: rejectedTaskId });
  expect(approvalStatus).toBe(409);
  await saveAcceptanceScreenshot(page, "human-veto-approver-blocked.png");
});

test("incomplete materials can be actively stopped before legal review without any dispatch", async ({ page }) => {
  const sends: string[] = [];
  page.on("request", request => {
    if (/\/api\/v1\/tasks\/[^/]+\/send$/.test(request.url())) sends.push(request.url());
  });
  const created = page.waitForResponse(response => response.url().endsWith("/api/v1/demos") && response.request().method() === "POST");
  await page.getByRole("button", { name: /在必要时主动停止/ }).click();
  const caseData = await (await created).json();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  const evaluated = page.waitForResponse(response => /\/api\/v1\/tasks\/[^/]+\/evaluate$/.test(response.url()));
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  const task = await (await evaluated).json();
  expect(task.risk.blockers.length).toBeGreaterThan(0);
  expect(task.review_status).toBe("pending");
  await expect(page.getByRole("button", { name: "停止任务", exact: true })).toBeEnabled();
  const stopped = page.waitForResponse(response => response.url().endsWith(`/tasks/${task.id}/stop`));
  await page.getByRole("button", { name: "停止任务", exact: true }).click();
  expect((await stopped).status()).toBe(200);
  await expect(page.getByRole("heading", { name: /任务已主动停止，本次请求不可继续/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新检验", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "停止任务", exact: true })).toBeDisabled();
  await page.goto("/");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByLabel("任务历史").selectOption(task.id);
  await expect(page.getByRole("heading", { name: /任务已主动停止，本次请求不可继续/ })).toBeVisible();
  const persisted = await page.evaluate(async ({caseId, taskId}) => {
    const data = await (await fetch(`/api/v1/cases/${caseId}`)).json();
    return data.tasks.find((item:any) => item.id === taskId);
  }, {caseId: caseData.id, taskId: task.id});
  expect(persisted.status).toBe("stopped");
  expect(persisted.approval).toBeNull();
  expect(persisted.request_hash).toBe(task.request_hash);
  expect(sends).toHaveLength(0);
  await saveAcceptanceScreenshot(page, "incomplete-materials-stopped.png");
});

test("technical reviewer can prepare a production rule draft but cannot publish or send", async ({ page }, testInfo) => {
  test.skip(testInfo.config.metadata.runtimeProfile !== "production", "Requires the isolated production profile");
  console.log("runtime-pack e2e: admin bootstrap");
  const create = await page.evaluate(async () => {
    const response = await fetch("/api/v1/users", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "runtime.technical", display_name: "运行规则技术员",
        role: "technical_reviewer", password: "runtime-password-123" }) });
    return { status: response.status, body: await response.text() };
  });
  expect([200, 409]).toContain(create.status);
  console.log("runtime-pack e2e: reviewer account ready");
  const observed: string[] = [];
  page.on("request", request => observed.push(`${request.method()} ${request.url()}`));
  await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" }));
  await page.goto("/");
  await page.getByLabel("用户名").fill("runtime.technical");
  await page.getByLabel("本地访问口令").fill("runtime-password-123");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  console.log("runtime-pack e2e: technical reviewer logged in");
  await page.getByRole("button", { name: "法学规则中心" }).click();
  await expect(page.getByRole("heading", { name: "法学规则中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "准备运行规则草稿" })).toBeVisible();
  console.log("runtime-pack e2e: runtime pack panel loaded");
  await page.getByLabel("明确适用范围").selectOption("request");
  const inputs = page.locator(".runtime-pack-workflow input[type=file]");
  await inputs.nth(0).setInputFiles(path.resolve("../packs/labor_product_draft.json"));
  await inputs.nth(1).setInputFiles(path.resolve("../docs/legal/reports/labor_product_import_report.json"));
  console.log("runtime-pack e2e: source and report selected");
  await page.getByRole("button", { name: "保存为运行库草稿" }).click();
  console.log("runtime-pack e2e: create request completed");
  await expect(page.getByText("已保存规则草稿", { exact: false })).toBeVisible();
  await expect(page.getByLabel("正式运行规则发布流程").getByText("draft", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "发布并激活规则" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "填写法学复核" })).toHaveCount(0);
  expect(observed.some(value => /\/tasks\/[^/]+\/send(?:\?|$)/.test(value))).toBe(false);
  expect(observed.some(value => /\/runtime-packs\/[^/]+\/publish(?:\?|$)/.test(value))).toBe(false);
});

test("synthetic case: disclosure, explicit approval, dispatch and source-linked result", async ({
  page,
}) => {
  for (const [username, role] of [["success.legal", "legal_reviewer"], ["success.approver", "approver"]]) {
    const response = await page.request.post("/api/v1/users", { data: {
      username, display_name: username, role, password: "success-review-password-123",
    }});
    expect([200, 409]).toContain(response.status());
  }
  const created = page.waitForResponse(response => response.url().endsWith("/api/v1/demos") && response.request().method() === "POST");
  await page.getByRole("button", { name: /01 完整披露流程/ }).click();
  const caseData = await (await created).json();
  await expect(page.getByRole("heading", { name: "事实与证据" })).toBeVisible();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(
    page.getByRole("heading", { name: /待人工复核，本次请求暂不可继续/ }),
  ).toBeVisible();
  await expect(page.getByText("独立风险攻击与红队实验待开发。", {exact:false})).toBeVisible();
  await expect(page.getByRole("button", { name: "审批当前完整请求" })).toHaveCount(0);
  await signIn(page, "success.legal", "success-review-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByRole("radio", { name: "允许处理（不授予发送权）", exact: true }).check();
  await page.locator(".legal-review fieldset.review-evidence-options").last().locator("input[type=checkbox]").first().check();
  await page.getByLabel("审批理由").fill("已核对内置合成材料及当前披露范围，允许本次离线模拟处理。");
  await page.getByLabel("事实前提").fill("只使用本场景固定合成事实及来源。");
  await page.getByLabel("权限判断").fill("法学复核仅解除复核限制，仍需独立审批。");
  await page.getByLabel("外部处理条件").fill("当前为demo离线模拟，不调用外部服务。");
  await page.getByLabel("最小化措施").fill("身份已一致替换，仅保留完成摘要所需事实。");
  await page.getByLabel("最终依据").fill("选定的演示控制项及当前合成事实。");
  await page.locator(".legal-review .check-grid input[type=checkbox]").first().check();
  await page.getByLabel("法源", { exact: true }).selectOption({ index: 0 });
  await page.locator(".legal-review .confirm-line input[type=checkbox]").check();
  await page.getByRole("button", { name: "提交法律复核结论" }).click();
  await expect(page.getByText("人工复核：已完成", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "审批当前完整请求" })).toHaveCount(0);

  await signIn(page, "success.approver", "success-review-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByRole("button", { name: "审批当前完整请求" }).click();
  await page.getByRole("button", { name: "已知悉并批准当前版本" }).click();

  // Sending is the case operator's action; an approver cannot assume that role.
  await signIn(page, "admin", "local-acceptance-only");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByRole("button", { name: "执行任务" }).click();
  await expect(page.getByRole("button", { name: "查看摘要与回链" })).toBeVisible();

  await signIn(page, "success.legal", "success-review-password-123");
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByRole("button", { name: "查看摘要与回链" }).click();
  await expect(page.getByText("本地预置结果")).toBeVisible();
  await expect(page.getByText("外发事实均已被引用。")).toBeVisible();
  const reviews = page.getByRole("button", { name: "已核对本项", exact: true });
  while (await reviews.count()) {
    await reviews.first().click();
    await expect(page.locator(".busy-bar")).toHaveCount(0);
  }
  await page.getByRole("button", { name: "确认最终结果", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "结果已确认", exact: true }),
  ).toBeDisabled();
  if (!(await page.getByText("回写待办").isVisible())) {
    await page.getByRole("button", { name: "依据与留痕" }).click();
  }
  await expect(page.getByText("回写待办")).toBeVisible();
  await expect(page.getByText("0 项未处理")).toBeVisible();
  await page.getByRole("button", { name: "回到原文" }).first().click();
  await expect(page.locator(".source-text")).toContainText("乔安");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.data/acceptance-result.png",
    fullPage: true,
  });
  await saveAcceptanceScreenshot(page, "successful-source-linked-result.png");
});

test("restoration empty state before dispatch", async ({ page }) => {
  await page.getByRole("button", { name: /01 完整披露流程/ }).click();
  await expect(page.getByRole("heading", { name: "事实与证据" })).toBeVisible();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await expect(page.getByRole("heading", { name: "逐项披露方案" })).toBeVisible();
  await page.getByRole("button", { name: /04\s*摘要与回链/ }).click();
  await expect(page.getByRole("heading", { name: "尚无摘要结果" })).toBeVisible();
  await expect(page.getByText("完成审批和调用后，结果会在此进入来源校核。")).toBeVisible();
});

test("demo keeps independent attack tools marked as planned", async ({ page }) => {
  await page.getByRole("button", { name: /01 完整披露流程/ }).click();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(page.getByText("独立风险攻击与红队实验待开发。", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "排队运行四类攻击" })).toHaveCount(0);
});

test("combination clues block approval without faking a risk pass", async ({
  page,
}) => {
  await page.getByRole("button", { name: /看见组合线索风险/ }).click();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(
    page.getByRole("heading", { name: /待人工复核，本次请求暂不可继续/ }),
  ).toBeVisible();
  await expect(
    page.getByText("组合线索风险：唯一岗位或公开事件仍保留"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批当前完整请求" }),
  ).toHaveCount(0);
});

test("formal DOCX upload, manual fact entry and formal outbound block", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.config.metadata.runtimeProfile !== "production", "Requires the isolated production profile");
  await page.getByRole("button", { name: "新建案件", exact: true }).click();
  await page.getByLabel("案件名称").fill("浏览器验收 · 正式材料");
  await page.getByRole("button", { name: "创建正式案件" }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles(path.resolve("../examples/synthetic_labor.docx"));
  await expect(page.locator(".source-text")).toContainText(
    "纯合成劳动争议材料",
  );
  await page.getByRole("button", { name: "添加事实" }).click();
  await page.getByLabel("事实内容").fill("纯合成劳动争议材料");
  await page.getByLabel("我已核对事实及其来源").check();
  await page.getByRole("button", { name: "保存事实", exact: true }).click();
  await expect(page.locator(".fact-card")).toHaveCount(1);
  await page.getByRole("button", { name: "正式云端摘要任务（仅生成草案）", exact: true }).click();
  const evaluated = page.waitForResponse(response =>
    /\/api\/v1\/tasks\/[^/]+\/evaluate$/.test(response.url()) && response.request().method() === "POST");
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  expect((await evaluated).status()).toBe(200);
  await expect(page.getByText("适用规则尚未正式发布")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /待人工复核，本次请求暂不可继续/ }),
  ).toBeVisible();
});

test("dashboard layout at desktop and mobile, capabilities remain honest", async ({
  page,
}) => {
  await page.screenshot({
    path: "../.data/acceptance-dashboard.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "运行配置", exact: true }).click();
  await expect(page.locator(".capability").getByText("已开发", { exact: true })).toHaveCount(8);
  await expect(page.locator(".capability").getByText("边侧小模型", { exact: true })).toBeVisible();
  await expect(page.locator(".capability").getByText("网络隔离", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "云端大模型", exact: true })).toBeVisible();
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "PUT" && request.url().endsWith("/api/v1/settings")) writes.push(request.url()); });
  await page.getByLabel("边侧模型名称", { exact: true }).fill("recording-local-model");
  await page.getByRole("button", { name: "保存运行配置", exact: true }).click();
  await expect(page.getByText("页面配置已保存。", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "运行配置", exact: true }).click();
  await expect(page.getByLabel("边侧模型名称", { exact: true })).toHaveValue("recording-local-model");
  expect(writes).toHaveLength(0);
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  await page.screenshot({
    path: "../.data/acceptance-mobile.png",
    fullPage: true,
  });
});

test("dialog keyboard behavior and accessible control names", async ({ page }) => {
  const trigger=page.getByRole("button",{name:"新建案件",exact:true});
  await trigger.click();
  await expect(page.getByRole("dialog")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();
  const unnamed=await page.locator("button").evaluateAll(buttons=>buttons.filter(button=>
    !(button.getAttribute("aria-label")||button.getAttribute("title")||button.textContent?.trim())).length);
  expect(unnamed).toBe(0);
  const unlabelled=await page.locator("input,select,textarea").evaluateAll(controls=>controls.filter(control=>
    !(control.getAttribute("aria-label")||control.getAttribute("aria-labelledby")||(control as HTMLInputElement).labels?.length)).length);
  expect(unlabelled).toBe(0);
  await page.emulateMedia({reducedMotion:"reduce"});
  const duration=await page.locator(".primary").first().evaluate(element=>getComputedStyle(element).transitionDuration);
  const seconds=duration.split(",").map(value=>value.trim().endsWith("ms")
    ? Number.parseFloat(value)/1000:Number.parseFloat(value));
  expect(Math.max(...seconds)).toBeLessThanOrEqual(.01);
});

test("five-viewport structural visual baseline", async ({page},testInfo)=>{
  const viewport=page.viewportSize()!;
  await expect(page.locator(".work-panel").or(page.locator(".dashboard"))).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  expect(overflow).toBe(false);
  if(viewport.width<=900){
    await page.getByRole("button",{name:"01 完整披露流程"}).click();
    await page.getByRole("button",{name:"原始材料",exact:true}).click();
    await expect(page.locator(".source-panel")).toBeVisible();
    await expect(page.locator(".work-panel")).toBeHidden();
    await page.getByRole("button",{name:"案件工作区",exact:true}).click();
    await expect(page.locator(".work-panel")).toBeVisible();
    await page.getByRole("button",{name:"依据与留痕",exact:true}).click();
    await expect(page.locator(".context-panel")).toBeVisible();
  }
  await testInfo.attach(`layout-${viewport.width}.png`,{body:await page.screenshot({fullPage:true}),contentType:"image/png"});
});
