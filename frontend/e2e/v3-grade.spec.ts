import {test, expect} from "@playwright/test";

test("仅正式请求的法学复核人可登记，不产生审批或发送", async ({page}) => {
  for (const suffix of ["?role=approver", "?role=admin", "?profile=demo", "?no-guard=1"]) {
    await page.goto(`/test-fixtures/v3-grade.html${suffix}`);
    await expect(page.getByText("登记当前请求的法学等级")).toHaveCount(0);
  }
  await page.goto("/test-fixtures/v3-grade.html");
  await page.getByText("登记当前请求的法学等级").click();
  const button=page.getByRole("button",{name:"登记等级，不发送"});
  await expect(button).toBeDisabled();
  await page.getByLabel("法学等级").selectOption("L2");
  await button.click();
  await expect(page.getByRole("status")).toContainText("仍需通过正式门禁和具名审批");
  const calls=JSON.parse(await page.getByTestId("calls").textContent() || "[]");
  expect(calls).toHaveLength(2);
  expect(calls[0].path).toBe("/tasks/synthetic-task/v3-grade-assessment");
  expect(calls[0].body).toEqual({request_hash:"a".repeat(64),grade:"L2"});
  expect(calls[1].path).toBe("/tasks/synthetic-task/formal-release/check");
  expect(calls.some((call:any)=>/\/send$|\/approve$/.test(call.path))).toBe(false);
});

test("没有法学复核时不能登记", async ({page}) => {
  await page.goto("/test-fixtures/v3-grade.html?unreviewed=1");
  await page.getByText("登记当前请求的法学等级").click();
  await expect(page.getByText("请先由本人完成当前请求的法学复核。")).toBeVisible();
  await expect(page.getByLabel("法学等级")).toBeDisabled();
});

test("等级已登记但后续检查失败时不重复提交", async ({page}) => {
  await page.goto("/test-fixtures/v3-grade.html?check-error=1");
  await page.getByText("登记当前请求的法学等级").click();
  await page.getByLabel("法学等级").selectOption("L3");
  await page.getByRole("button",{name:"登记等级，不发送"}).click();
  await expect(page.getByRole("status")).toContainText("正式门禁检查未完成");
  await expect(page.getByRole("button",{name:"登记等级，不发送"})).toBeDisabled();
});

test("旧请求等级不能阻止新请求重新登记", async ({page}) => {
  await page.goto("/test-fixtures/v3-grade.html?old=1");
  await page.getByText("登记当前请求的法学等级").click();
  await expect(page.getByLabel("法学等级")).toBeEnabled();
});

test("服务端拒绝时保留选择并展示原因", async ({page}) => {
  await page.goto("/test-fixtures/v3-grade.html?error=1");
  await page.getByText("登记当前请求的法学等级").click();
  await page.getByLabel("法学等级").selectOption("L1");
  await page.getByRole("button",{name:"登记等级，不发送"}).click();
  await expect(page.getByRole("alert")).toContainText("模拟拒绝");
  await expect(page.getByLabel("法学等级")).toHaveValue("L1");
});

test("风险工作台实际接入等级登记，不自动发送", async ({page}) => {
  await page.goto("/test-fixtures/v3-grade.html?workspace=1");
  await page.getByText("登记当前请求的法学等级").click();
  await page.getByLabel("法学等级").selectOption("L1");
  await page.getByRole("button", {name:"登记等级，不发送"}).click();
  await expect(page.getByText("等级已登记，仍需通过正式门禁和具名审批；此操作不发送。")).toBeVisible();
  const calls=JSON.parse(await page.getByTestId("calls").textContent() || "[]");
  expect(calls.some((call:any)=>/\/send$|\/approve$/.test(call.path))).toBe(false);
});
