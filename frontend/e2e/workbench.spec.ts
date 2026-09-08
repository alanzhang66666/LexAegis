import { test, expect } from "@playwright/test";
import path from "node:path";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("本地访问口令").fill("local-acceptance-only");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
});

test("synthetic case: disclosure, explicit approval, dispatch and source-linked result", async ({
  page,
}) => {
  await page.getByRole("button", { name: /01 完整披露流程/ }).click();
  await expect(page.getByRole("heading", { name: "事实与证据" })).toBeVisible();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(
    page.getByRole("heading", { name: "当前门禁允许进入审批" }),
  ).toBeVisible();
  await expect(page.getByText("未运行 · 阻断")).toHaveCount(4);
  await page.getByRole("button", { name: "审批当前完整请求" }).click();
  await page.getByRole("button", { name: "已知悉并批准当前版本" }).click();
  await page.getByRole("button", { name: "执行模拟调用" }).click();
  await page.getByRole("button", { name: "查看摘要与回链" }).click();
  await expect(page.getByText("模拟结果 · 非模型生成")).toBeVisible();
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
  await expect(page.locator(".source-text")).toContainText("林澄");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.data/acceptance-result.png",
    fullPage: true,
  });
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

test("combination clues block approval without faking a risk pass", async ({
  page,
}) => {
  await page.getByRole("button", { name: /02 看见组合线索风险/ }).click();
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(
    page.getByRole("heading", { name: "当前请求已阻断" }),
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
}) => {
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
  await page.getByRole("button", { name: "云端摘要任务", exact: true }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  await expect(page.getByText("适用规则尚未正式发布")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "当前请求已阻断" }),
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
  await expect(
    page.getByText("未运行、错误和不确定均不算通过"),
  ).toBeVisible({ timeout: 15000 });
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
