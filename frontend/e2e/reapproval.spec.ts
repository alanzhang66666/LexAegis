import { test, expect } from "@playwright/test";

test("只有正式未排队请求的审批人可见，提交须填写原因", async ({page}) => {
  for (const query of ["role=admin", "role=legal_reviewer", "status=queued", "profile=demo"]) {
    await page.goto(`/test-fixtures/reapproval.html?${query}`);
    await expect(page.getByText("撤销旧许可并准备重新审批")).toHaveCount(0);
  }
  await page.goto("/test-fixtures/reapproval.html");
  await page.getByText("撤销旧许可并准备重新审批").click();
  const button = page.getByRole("button", {name:"撤销旧许可并返回复核"});
  await expect(button).toBeDisabled();
  await page.getByLabel("重新审批原因").fill("  证据版本变化  ");
  await button.click();
  await expect(page.getByTestId("task-state")).toHaveText("review");
  const payload = JSON.parse((await page.getByTestId("request").textContent()) || "{}");
  expect(payload).toEqual({path:"/tasks/synthetic-task/formal-release/reapproval",method:"POST",
    body:{request_hash:"a".repeat(64),reason:"证据版本变化"}});
  await expect(page.getByText("撤销旧许可并准备重新审批")).toHaveCount(0);
});

test("接口拒绝时保留原因并提示错误；刷新失败时禁止重复提交", async ({page}) => {
  await page.goto("/test-fixtures/reapproval.html?mode=error");
  await page.getByText("撤销旧许可并准备重新审批").click();
  await page.getByLabel("重新审批原因").fill("原因");
  await page.getByRole("button", {name:"撤销旧许可并返回复核"}).click();
  await expect(page.getByRole("alert")).toHaveText("模拟服务器拒绝");
  await expect(page.getByLabel("重新审批原因")).toHaveValue("原因");
  await page.goto("/test-fixtures/reapproval.html?mode=refresh-error");
  await page.getByText("撤销旧许可并准备重新审批").click();
  await page.getByLabel("重新审批原因").fill("原因");
  await page.getByRole("button", {name:"撤销旧许可并返回复核"}).click();
  await expect(page.locator('p[role="status"]')).toContainText("不要重复提交");
  await expect(page.getByRole("button", {name:"撤销旧许可并返回复核"})).toBeDisabled();
});

test("风险工作台实际接入入口且不自动审批", async ({page}, testInfo) => {
  await page.goto("/test-fixtures/reapproval.html?workspace=1");
  await page.getByText("撤销旧许可并准备重新审批").click();
  await page.getByLabel("重新审批原因").fill("原许可对应旧证据");
  await page.screenshot({path:testInfo.outputPath("reapproval-workspace.png"),fullPage:true});
  await page.getByRole("button", {name:"撤销旧许可并返回复核"}).click();
  await expect(page.getByTestId("task-state")).toHaveText("review");
  await expect(page.getByText("撤销旧许可并准备重新审批")).toHaveCount(0);
  await expect(page.getByRole("button", {name:"审批当前完整请求"})).toHaveCount(0);
});

test("同请求重新批准并签发新许可后可再次发起撤销", async ({page}) => {
  await page.goto("/test-fixtures/reapproval.html?mode=reapprove");
  await page.getByText("撤销旧许可并准备重新审批").click();
  await page.getByLabel("重新审批原因").fill("第一次变更");
  await page.getByRole("button", {name:"撤销旧许可并返回复核"}).click();
  await expect(page.getByTestId("task-state")).toHaveText("review");
  await page.getByRole("button", {name:"模拟签发新许可"}).click();
  await page.getByText("撤销旧许可并准备重新审批").click();
  await page.getByLabel("重新审批原因").fill("第二次变更");
  await expect(page.getByRole("button", {name:"撤销旧许可并返回复核"})).toBeEnabled();
});
