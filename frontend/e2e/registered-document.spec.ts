import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { SYSTEM_FULL_NAME } from "../src/branding";

test("private registration permits synthetic upload, extraction and review without a vendor send", async ({page}) => {
  test.skip(!process.env.LEX_REGISTERED_E2E_URL, "Explicit isolated integration runtime required");
  const accounts=JSON.parse(readFileSync(process.env.LEX_REGISTERED_E2E_ACCOUNTS!,"utf8"));
  await page.goto("/");
  await expect(page).toHaveTitle(SYSTEM_FULL_NAME);
  await page.getByLabel("用户名").fill(accounts.case_operator.username);
  await page.getByLabel("本地访问口令").fill(accounts.case_operator.password);
  await page.getByRole("button",{name:"进入工作台",exact:true}).click();
  await page.getByRole("button",{name:/登记文档全流程联调/}).click();
  await page.getByLabel("上传案件材料").setInputFiles(process.env.LEX_REGISTERED_E2E_DOCUMENT!);
  await expect(page.getByRole("button",{name:/\.docx v1 · 已解析/}).first()).toBeVisible({timeout:45000});
  await page.getByRole("button",{name:"边侧提取",exact:true}).click();
  const fact=page.locator("article.fact-card").filter({has:page.getByText("1,200元",{exact:true})}).first();
  await expect(fact).toBeVisible({timeout:45000});
  await expect(fact.getByText("边侧模型提取",{exact:true})).toBeVisible();
  await fact.getByRole("button",{name:"查看原文依据",exact:true}).click();
  await fact.getByRole("button",{name:"编辑",exact:true}).click();
  await page.getByRole("checkbox",{name:"我已核对事实及其来源",exact:true}).check();
  await page.getByRole("button",{name:"保存事实",exact:true}).click();
  await expect(fact.getByText("已确认",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"云端摘要任务（仅生成草案）",exact:true}).click();
  await expect(page.getByRole("button",{name:"检验风险并冻结请求",exact:true})).toBeVisible();
  // No send click: this instance has zero provider credentials and zero budget.
});
