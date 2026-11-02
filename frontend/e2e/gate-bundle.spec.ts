import {test, expect} from "@playwright/test";

test("四门与全局阻断显示原始原因，不宣称通过", async ({page}) => {
  await page.goto("/test-fixtures/gate-view.html?case=blocked");
  const box = page.getByRole("region", {name:"四门复核概览"});
  await expect(box.getByText("仅供查看，不构成外发批准")).toBeVisible();
  for (const gate of ["G-L","G-D","G-H","G-S"]) await expect(box.getByText(gate, {exact:true})).toBeVisible();
  await expect(box.getByText("待处理 1 项")).toHaveCount(2);
  await expect(box.getByText("未单项验证")).toHaveCount(2);
  await box.locator("details").first().locator("summary").click();
  await expect(box.getByText("服务商复核记录缺失")).toBeVisible();
  await expect(box.getByText("当前请求缺少有效隔离收据")).toBeVisible();
  await expect(box.getByText("已通过", {exact:true})).toHaveCount(0);
});

test("空、过期、不一致和损坏的数据不会显示为已验证", async ({page}) => {
  for (const kind of ["missing","malformed"]) {
    await page.goto(`/test-fixtures/gate-view.html?case=${kind}`);
    await expect(page.getByText("当前未取得完整的门禁概览，请重新检查当前请求。")).toBeVisible();
  }
  for (const kind of ["stale","wrong-hash"]) {
    await page.goto(`/test-fixtures/gate-view.html?case=${kind}`);
    await expect(page.getByText("门禁概览与当前请求不一致或已过期，请重新检查当前请求。")).toBeVisible();
    await expect(page.getByText("服务商复核记录缺失")).toHaveCount(0);
  }
  await page.goto("/test-fixtures/gate-view.html?case=empty");
  await expect(page.getByText("未单项验证")).toHaveCount(4);
});

test("工作台展示只读概览，不改变旧审批与发送控制", async ({page}, testInfo) => {
  await page.goto("/test-fixtures/gate-view.html?case=workspace");
  await expect(page.getByRole("region",{name:"四门复核概览"})).toBeVisible();
  await expect(page.getByText("正式放行门：未满足，禁止审批或发送")).toBeVisible();
  await expect(page.getByRole("button",{name:"审批当前完整请求"})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"发送至已批准云端"})).toHaveCount(0);
  await page.getByText("上次检查的证据版本诊断（仅供查看）").click();
  await expect(page.getByText("G5：版本差异：规则版本")).toBeVisible();
  await page.screenshot({path:testInfo.outputPath("workspace.png"),fullPage:true});
});

test("自动策略仅显示核验入口，不声称门禁已通过", async ({page}, testInfo) => {
  await page.goto("/test-fixtures/gate-view.html?case=workspace-auto");
  await expect(page.getByText("正式放行门：待完整核验，不代表可发送")).toBeVisible();
  await expect(page.getByRole("button", {name:"核验并审批当前完整请求"})).toBeVisible();
  await expect(page.getByRole("button", {name:"发送至已批准云端"})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath("auto-policy-workspace.png"),fullPage:true});
  await page.goto("/test-fixtures/gate-view.html?case=workspace-auto-legal");
  await expect(page.getByRole("button", {name:"核验并审批当前完整请求"})).toHaveCount(0);
});

test("诊断仅显示版本差异，不构成签署、批准或复用", async ({page}) => {
  await page.goto("/test-fixtures/gate-view.html?case=blocked");
  await page.getByText("上次检查的证据版本诊断（仅供查看）").click();
  await expect(page.getByText("以下为上次检查的结果；证据变更后请重新检查。指纹只用于提示版本变化，未验证签署、效期或法律适用性，不能作为批准或证据复用依据。")).toBeVisible();
  await expect(page.getByText("G5：版本差异：规则版本")).toBeVisible();
  await expect(page.getByText("G9 诊断信息不完整，未生成指纹")).toBeVisible();
  for (const kind of ["scope-stale", "scope-forged"]) {
    await page.goto(`/test-fixtures/gate-view.html?case=${kind}`);
    await expect(page.getByText("证据版本诊断当前不可用；仍按原有门禁核验。")).toBeVisible();
    await expect(page.getByText("上次检查的证据版本诊断（仅供查看）")).toHaveCount(0);
  }
});

test("键盘可展开和收起门禁明细", async ({page}) => {
  await page.goto("/test-fixtures/gate-view.html?case=blocked");
  const first = page.getByRole("region", {name:"四门复核概览"}).locator("details").first();
  await first.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(first.getByText("服务商复核记录缺失")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(first.getByText("服务商复核记录缺失")).toBeHidden();
});

test("窄屏单列与桌面两列均无横向溢出", async ({page}, testInfo) => {
  for (const viewport of [{width:1280,height:900},{width:390,height:844}]) {
    await page.setViewportSize(viewport);
    await page.goto("/test-fixtures/gate-view.html?case=blocked");
    await expect(page.getByRole("region",{name:"四门复核概览"})).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow).toBe(false);
    await page.screenshot({path:testInfo.outputPath(`gate-${viewport.width}.png`),fullPage:true});
  }
});
