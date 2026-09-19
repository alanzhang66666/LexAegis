import { test, expect } from "@playwright/test";
import path from "node:path";

test("production formal intake stays bound and unapproved when authoritative build evidence is missing", async ({ page }, testInfo) => {
  test.skip(testInfo.config.metadata.runtimeProfile !== "production", "Production-only formal release evidence intake.");
  await page.goto("/");
  await page.getByLabel("本地访问口令").fill("local-acceptance-only");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  await page.getByRole("button", { name: "新建案件", exact: true }).click();
  await page.getByLabel("案件名称").fill("正式证据登记界面验收");
  const caseCreated = page.waitForResponse(response => response.url().endsWith("/api/v1/cases") && response.request().method()==="POST");
  await page.getByRole("button", { name: "创建正式案件" }).click();
  const caseData = await (await caseCreated).json();
  await page.locator("input[type=file]").setInputFiles(path.resolve("../examples/synthetic_labor.docx"));
  await expect(page.locator(".source-text")).toContainText("纯合成劳动争议材料");
  await page.getByRole("button", { name: "添加事实" }).click();
  await page.getByLabel("事实内容").fill("纯合成劳动争议材料");
  await page.getByLabel("我已核对事实及其来源").check();
  await page.getByRole("button", { name: "保存事实", exact: true }).click();
  await expect(page.locator(".fact-card")).toHaveCount(1);
  await page.getByRole("button", { name: "正式云端摘要任务（仅生成草案）" }).click();
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  const taskId = await page.getByLabel("任务历史").inputValue();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByLabel("任务历史").selectOption(taskId);
  await expect(page.getByRole("heading", { name: "正式放行证据与人工收据" })).toBeVisible();
  await expect(page.getByText("每份收据须绑定当前请求和具名人员")).toBeVisible();
  const pendingContext = page.getByText(/当前正式证据上下文不可用/);
  const readOnlyContext = page.getByText(/当前角色为.*只可查看证据与收据/).first();
  await expect(pendingContext.or(readOnlyContext)).toBeVisible();
  const sendButtons = page.getByRole("button", { name: /发送至已批准云端/ });
  await expect(sendButtons).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("formal-intake-unapproved.png"), fullPage: true });
});

test("production formal intake uses exact actor, pending default and frozen G1 bindings with a test stub", async ({ page }, testInfo) => {
  test.skip(testInfo.config.metadata.runtimeProfile !== "production", "Production-only formal release evidence intake.");
  const context = {
    task_id: "stub-task", request_hash: "a".repeat(64), tuple: { case_id: "CASE-STUB", purpose: "R_fact_summary", recipient: "provider-stub" },
    bound_versions: { materials: "materials-hash", rules: "rules-hash", task: "3", mapping: "2", ledger: "4", combination: "combination-hash" },
    build_manifest_hash: "build-hash", actor: { user_id: "user-legal", username: "intake.legal", actor: "intake.legal", role: "legal_reviewer" },
    facts: [{ id: "fact-wire-1", field: "entity", text: "合成主体事实", source_ids: ["block-1"] }],
    gates: [
      { gate_id: "G1", required_template_kinds: ["法01"], templates: [{ template_kind: "法01", required_role: "legal_reviewer", required_for_gate: true }] },
      { gate_id: "G7", required_template_kinds: ["法08"], templates: [{ template_kind: "法08", required_role: "legal_reviewer", required_for_gate: true, technical_template: "技04" }] },
    ], g2_authorization_statement: "仅允许此次合成请求用于摘要", isolation: { attester_role: "technical_reviewer", legal_confirmation_role: "legal_reviewer", confirmation_gate_id: "G8" },
  };
  const artifacts = [
    { id: "template-law01", template_kind: "法01", source_path_hint: "law01.docx", content_hash: "1".repeat(64) },
    { id: "evidence-material", template_kind: "法01", source_path_hint: "material.pdf", content_hash: "2".repeat(64) },
    { id: "technical-04", template_kind: "技04", source_path_hint: "isolation-tech04.json", content_hash: "3".repeat(64) },
  ];
  let saved: any[] = [];
  let submittedReceipt:any;
  let activeActor: any = context.actor;
  let isolationPostCount = 0;
  await page.route("**/api/v1/tasks/*/formal-release/intake-context", route => route.fulfill({ json: { ...context, actor: activeActor, task_id: new URL(route.request().url()).pathname.split("/")[4] } }));
  await page.route("**/api/v1/formal-release", route => route.fulfill({ json: { policies: [], artifacts, receipts: saved,
    isolation_receipts: [{ id: "isolation-stub", request_hash: context.request_hash, tuple: context.tuple, status: "pending_legal_confirmation", attested_by: "tech-user" }], grants: [] } }));
  await page.route("**/api/v1/formal-release/receipts", async route => {
    const body = route.request().postDataJSON();
    submittedReceipt = body;
    const receipt = { id: "receipt-stub", ...body };
    saved = [...saved, receipt];
    await route.fulfill({ json: receipt });
  });
  await page.route("**/api/v1/formal-release/isolation", async route => {
    isolationPostCount += 1;
    await route.fulfill({ json: { id: "unexpected-isolation-post", ...route.request().postDataJSON() } });
  });

  await page.goto("/");
  await page.getByLabel("本地访问口令").fill("local-acceptance-only");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  const account = await page.evaluate(async () => {
    const response = await fetch("/api/v1/users", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "intake.legal", display_name: "登记验收法学人员", role: "legal_reviewer", password: "intake-password-123" }) });
    return response.status;
  });
  expect([200, 409]).toContain(account);
  const technicalAccount = await page.evaluate(async () => {
    const response = await fetch("/api/v1/users", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "intake.technical", display_name: "登记验收技术人员", role: "technical_reviewer", password: "technical-password-123" }) });
    return response.status;
  });
  expect([200, 409]).toContain(technicalAccount);
  await page.getByRole("button", { name: "新建案件", exact: true }).click();
  await page.getByLabel("案件名称").fill("运行库证据绑定验收");
  const caseCreated = page.waitForResponse(response => response.url().endsWith("/api/v1/cases") && response.request().method()==="POST");
  await page.getByRole("button", { name: "创建正式案件" }).click();
  const caseData = await (await caseCreated).json();
  await page.locator("input[type=file]").setInputFiles(path.resolve("../examples/synthetic_labor.docx"));
  await expect(page.locator(".source-text")).toContainText("纯合成劳动争议材料");
  await page.getByRole("button", { name: "添加事实" }).click();
  await page.getByLabel("事实内容").fill("纯合成劳动争议材料");
  await page.getByLabel("我已核对事实及其来源").check();
  await page.getByRole("button", { name: "保存事实", exact: true }).click();
  await page.getByRole("button", { name: "正式云端摘要任务（仅生成草案）" }).click();
  const evaluateResponsePromise=page.waitForResponse(response=>/\/api\/v1\/tasks\/[^/]+\/evaluate$/.test(response.url())&&response.request().method()==="POST");
  await page.getByRole("button", { name: "检验风险并冻结请求" }).click();
  const evaluateResponse=await evaluateResponsePromise;
  expect(evaluateResponse.status(),await evaluateResponse.text()).toBe(200);
  const taskId = await page.getByLabel("任务历史").inputValue();
  const taskSnapshot=await page.evaluate(async ({caseId,taskId})=>{
    const response=await fetch(`/api/v1/cases/${caseId}`,{credentials:"same-origin"});const data=await response.json();
    return (data.tasks||[]).find((item:any)=>item.id===taskId);
  },{caseId:caseData.id,taskId});
  expect(taskSnapshot?.request_hash).toMatch(/^[a-f0-9]{64}$/);
  context.request_hash=taskSnapshot.request_hash;context.tuple.case_id=caseData.id;
  const validFrom=new Date(Date.now()-60_000).toISOString(),validUntil=new Date(Date.now()+7*24*60*60_000).toISOString();
  saved=[{id:"g8-signed-by-me",gate_id:"G8",tuple:context.tuple,request_hash:context.request_hash,conclusion:"pass",confirmed_role:"legal_reviewer",confirmed_by:"intake.legal",confirmed_at:validFrom,valid_from:validFrom,valid_until:validUntil},
    {id:"g8-signed-by-other",gate_id:"G8",tuple:context.tuple,request_hash:context.request_hash,conclusion:"pass",confirmed_role:"legal_reviewer",confirmed_by:"another.legal",confirmed_at:validFrom,valid_from:validFrom,valid_until:validUntil}];
  await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" }));
  await page.goto("/");
  await page.getByLabel("用户名").fill("intake.legal");
  await page.getByLabel("本地访问口令").fill("intake-password-123");
  await page.getByRole("button", { name: "进入工作台" }).click();
  activeActor={user_id:"user-legal",username:"intake.legal",actor:"intake.legal",role:"legal_reviewer"};
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByLabel("任务历史").selectOption(taskId);
  await expect(page.getByRole("heading", { name: "正式放行证据与人工收据" })).toBeVisible();
  await expect(page.getByLabel("G1 法01 人工结论")).toHaveValue("pending");
  await expect(page.getByRole("combobox", { name: "证据模板类别" })).toContainText("技04");
  await expect(page.getByLabel("isolation-stub 选择本人 G8 收据").locator("option")).toHaveCount(2);
  await page.getByLabel("isolation-stub 选择本人 G8 收据").selectOption("g8-signed-by-me");
  await page.getByLabel("模板原件").first().selectOption("template-law01");
  await page.locator(".intake-template").first().locator("fieldset.intake-artifacts").nth(1).locator("input").first().check();
  await page.getByLabel("有效期起").first().fill("2030-04-01T10:30");
  await page.getByLabel("有效期止").first().fill("2030-04-10T10:30");
  await page.getByRole("button", { name: /登记pending 人工收据/ }).first().click();
  const body = submittedReceipt;
  expect(body).toMatchObject({ gate_id: "G1", template_kind: "法01", conclusion: "pending", request_hash: null,
    confirmed_role: "legal_reviewer", tuple: context.tuple, bound_versions: context.bound_versions,
    template_artifact_id: "template-law01", adopted_fact_ids: ["fact-wire-1"] });
  expect(body.evidence_artifact_ids).toContain("template-law01");
  expect(body.valid_from).toMatch(/^2030-04-01T/);
  expect(body.valid_until).toMatch(/^2030-04-10T/);
  await page.screenshot({ path: testInfo.outputPath("formal-intake-pending-g1.png"), fullPage: true });

  await page.evaluate(() => fetch("/api/v1/logout", { method: "POST", credentials: "same-origin" }));
  await page.goto("/");
  await page.getByLabel("用户名").fill("intake.technical");
  await page.getByLabel("本地访问口令").fill("technical-password-123");
  await page.getByRole("button", { name: "进入工作台" }).click();
  activeActor={user_id:"user-technical",username:"intake.technical",actor:"intake.technical",role:"technical_reviewer"};
  await expect(page.getByRole("heading", { name: "案件工作台" })).toBeVisible();
  await page.locator(".case-row").filter({ hasText: caseData.id }).click();
  await page.getByRole("button", { name: /03 风险与审批/ }).click();
  await page.getByLabel("任务历史").selectOption(taskId);
  await expect(page.getByRole("heading", { name: "技术隔离证据（人工测量结果 JSON）" })).toBeVisible();
  const valid = { id:"isolation-input", tuple:context.tuple, request_hash:context.request_hash, build_manifest_hash:context.build_manifest_hash,
    deployment_mode:"isolated", deployment_identity_hash:"identity-hash", compose_hash:"compose-hash", image_digests:{api:"sha256:api"},
    api_no_egress:true,worker_no_egress:true,gateway_no_case_volume:true,redteam_no_secrets:true,benchmark_no_secrets:true,
    probe_output_hash:"probe-hash",host_firewall_evidence_hash:"firewall-hash",supply_chain_evidence_hash:"supply-hash",
    status:"pending_legal_confirmation",legal_confirmation_receipt_id:null };
  for (const [field,value] of [["tuple",{case_id:"OTHER",purpose:"R_fact_summary",recipient:"provider-stub"}],
    ["request_hash","b".repeat(64)],["build_manifest_hash","other-build"],["status","valid"]] as const) {
    const document={...valid,[field]:value};
    await page.locator(".intake-isolation input[type=file]").setInputFiles({name:`${field}.json`,mimeType:"application/json",buffer:Buffer.from(JSON.stringify(document))});
    await page.getByRole("button", { name: "登记待法学确认的隔离收据" }).click();
    await expect(page.getByRole("alert").filter({hasText:/隔离证据的案件|pending_legal_confirmation/})).toBeVisible();
  }
  expect(isolationPostCount).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("formal-intake-isolation-rejects-mismatched-bindings.png"), fullPage: true });
});
