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
    page.getByRole("heading", { name: "合成演示请求可审批" }),
  ).toBeVisible();
  await expect(page.getByText("未实现 · 未运行")).toHaveCount(4);
  await page.getByRole("button", { name: "审批当前完整请求" }).click();
  await page.getByRole("button", { name: "已知悉并批准当前版本" }).click();
  await page.getByRole("button", { name: "执行模拟调用" }).click();
  await page.getByRole("button", { name: "查看摘要与回链" }).click();
  await expect(page.getByText("模拟结果 · 非模型生成")).toBeVisible();
  const reviews = page.getByRole("button", { name: "已核对本项", exact: true });
  while (await reviews.count()) {
    await reviews.first().click();
    await expect(page.locator(".busy-bar")).toHaveCount(0);
  }
  await page.getByRole("button", { name: "确认最终结果", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "结果已确认", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "回到原文" }).first().click();
  await expect(page.locator(".source-text")).toContainText("林澄");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "../.data/acceptance-result.png",
    fullPage: true,
  });
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
  await page.getByRole("button", { name: "生成披露方案", exact: true }).click();
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
    page.getByText("四类策略为占位；正式案件外发保持阻断"),
  ).toBeVisible();
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
