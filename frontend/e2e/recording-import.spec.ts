import { test, expect } from '@playwright/test';
import path from 'node:path';
import { readdirSync } from 'node:fs';

test('administrator can review both imported local cases without changing accounts', async ({ page }) => {
  const directory = path.resolve('../data/recording_adapted');
  const files = readdirSync(directory).filter(name => name.endsWith('.docx')).sort();
  await page.goto('/');
  await page.getByLabel('本地访问口令').fill(process.env.LEX_TEST_PASSWORD || 'local-acceptance-only');
  await page.getByRole('button', { name: '进入工作台' }).click();
  for (const index of [1, 2]) {
    await page.getByLabel('导入 Word 材料', { exact: true }).setInputFiles(path.join(directory, files[index]));
    await expect(page.getByRole('heading', { name: new RegExp(`LA-00${index + 1}`) })).toBeVisible();
    await page.getByRole('button', { name: '03 风险与审批', exact: true }).click();
    await page.getByRole('button', { name: '进入人工审核', exact: true }).click();
    await expect(page.getByLabel('审批理由', { exact: true })).toBeVisible();
    await page.getByRole('radio', { name: index === 1 ? '否决本次请求' : '允许处理（不授予发送权）', exact: true }).check();
    const reason = index === 1 ? '补贴与参保组合超出必要范围，关系起算日冲突未解决。' : '已核对管理行为与证据类别，候选内容仅包含最小必要信息。';
    for (const field of ['审批理由', '事实前提', '权限判断', '外部处理条件', '最小化措施', '最终依据']) {
      await page.getByLabel(field, { exact: true }).fill(reason);
    }
    await page.getByRole('group', { name: '本次复核证据（必选）', exact: true }).getByRole('checkbox').first().check();
    await page.locator('.legal-review .check-grid input[type=checkbox]').first().check();
    await page.getByLabel('法源', { exact: true }).selectOption({ index: 0 });
    await page.locator('.legal-review .confirm-line input').check();
    const reviewed = page.waitForResponse(response => response.url().includes('/demos/tasks/') && response.url().endsWith('/legal-review'));
    await page.getByRole('button', { name: index === 1 ? '提交否决并阻断本次请求' : '提交法律复核结论', exact: true }).click();
    expect((await reviewed).status()).toBe(200);
    if (index === 1) {
      await expect(page.locator('.review-status-strip')).toContainText('已否决');
      await expect(page.getByRole('button', { name: '审批当前完整请求', exact: true })).toHaveCount(0);
    } else {
      await expect(page.locator('.review-status-strip')).toContainText('已完成');
      await page.getByRole('button', { name: '审批当前完整请求', exact: true }).click();
      const approved = page.waitForResponse(response => response.url().includes('/demos/tasks/') && response.url().endsWith('/approve'));
      await page.getByRole('button', { name: '已知悉并批准当前版本', exact: true }).click();
      expect((await approved).status()).toBe(200);
      await page.getByRole('button', { name: '执行任务', exact: true }).click();
      await expect(page.getByRole('button', { name: '查看摘要与回链', exact: true })).toBeVisible({ timeout: 15000 });
    }
    await page.getByRole('button', { name: '返回案件列表', exact: true }).click();
  }
});

test('recording Word can be imported from list and material panel', async ({ page }) => {
  const directory = path.resolve('../data/recording_adapted');
  const files = readdirSync(directory).filter(name => name.endsWith('.docx')).sort();
  await page.goto('/');
  await page.getByLabel('本地访问口令').fill(process.env.LEX_TEST_PASSWORD || 'local-acceptance-only');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('heading', { name: '四个功能边界' })).toBeVisible();
  for (const name of ['材料与事实', '披露方案', '风险与审批', '摘要与回链']) {
    await expect(page.getByLabel('四个功能边界').getByRole('heading', { name, exact: true })).toBeVisible();
  }
  await expect(page.getByText(/解锁|锁定|三个案例入口/)).toHaveCount(0);
  await expect(page.getByLabel('本案阶段内容')).toHaveCount(0);
  const first = page.waitForResponse(r => r.url().endsWith('/demos/import'));
  await page.getByLabel('导入 Word 材料', { exact: true }).setInputFiles(path.join(directory, files[0]));
  expect((await first).status()).toBe(200);
  await expect(page.getByRole('heading', { name: /LA-001/ })).toBeVisible();
  for (const stage of [
    { name: '01 材料与事实', token: '主体设立时间与实际管理关系' },
    { name: '02 披露方案', token: '删除可反向定位的组合' },
    { name: '03 风险与审批', token: '当前材料包含可定位案件的组合线索' },
    { name: '04 摘要与回链', token: '系统判断不能进入外部处理' },
  ]) {
    await page.getByRole('button', { name: stage.name, exact: true }).click();
    await expect(page.getByLabel('当前流程材料')).toContainText(files[0]);
    await expect(page.getByLabel('当前流程材料').getByRole('button', { name: '查看完整原文' })).toBeVisible();
    await expect(page.getByLabel('本案阶段内容')).toContainText(stage.token);
    await expect(page.getByText(/解锁|锁定/)).toHaveCount(0);
  }
  await page.getByRole('button', { name: '01 材料与事实', exact: true }).click();
  const sourceTab = page.getByRole('button', { name: '原始材料', exact: true });
  if (await sourceTab.isVisible()) await sourceTab.click();
  await expect(page.locator('label.upload')).toBeVisible();
  await page.getByRole('button', { name: '阅读全文', exact: true }).click();
  await expect(page.getByLabel('完整材料正文')).toContainText('诉讼时间线');
  await expect(page.getByLabel('完整材料正文')).toContainText('工作年限');
  await page.getByRole('button', { name: '查看原文依据', exact: true }).first().click();
  await expect(page.getByLabel('完整材料正文')).toHaveCount(0);
  await expect(page.locator('.source-label')).toContainText('段落');
  await expect(page.getByRole('button', { name: '阅读全文', exact: true })).toBeVisible();
  await expect(page.locator('.source-text')).toContainText('劳动争议案');
  await page.screenshot({ path: 'test-results/recording-full-material.png', fullPage: true });
  const second = page.waitForResponse(r => r.url().endsWith('/demos/import'));
  await page.getByLabel('上传案件材料', { exact: true }).setInputFiles(path.join(directory, files[1]));
  expect((await second).status()).toBe(200);
  await expect(page.getByRole('heading', { name: /LA-002/ })).toBeVisible();
});

test('all three recording cases expose material-specific local tools', async ({ page }) => {
  const directory = path.resolve('../data/recording_adapted');
  const files = readdirSync(directory).filter(name => name.endsWith('.docx')).sort();
  const expected = [
    { heading: /LA-001/, timeline: '2021年6月8日', evidence: '柜台分摊费', issue: '用工主体与期间',
      stages: ['主体设立时间与实际管理关系', '保留争点结构', '当前材料包含可定位案件', '系统判断不能进入外部处理'] },
    { heading: /LA-002/, timeline: '2015年9月25日', evidence: '社会保险补贴', issue: '关系起算日差异',
      stages: ['店长管理、长期付款', '精确补贴组合与日期冲突', '技术检验后仍需人工判断', '人工复核否决后停止当前请求'] },
    { heading: /LA-003/, timeline: '2024年7月14日', evidence: '平台收入账单', issue: '站点经营主体',
      stages: ['实际管理与履行记录', '只保留角色、管理行为', '最小化内容可进入人工复核', '人工复核允许后可生成'] },
  ];
  await page.goto('/');
  await page.getByLabel('本地访问口令').fill(process.env.LEX_TEST_PASSWORD || 'local-acceptance-only');
  await page.getByRole('button', { name: '进入工作台' }).click();

  for (let index = 0; index < files.length; index += 1) {
    const input = index === 0
      ? page.getByLabel('导入 Word 材料', { exact: true })
      : page.getByLabel('上传案件材料', { exact: true });
    const imported = page.waitForResponse(response => response.url().endsWith('/demos/import'));
    await input.setInputFiles(path.join(directory, files[index]));
    expect((await imported).status()).toBe(200);
    await expect(page.getByRole('heading', { name: expected[index].heading })).toBeVisible();

    for (const [stageIndex, stage] of ['01 材料与事实', '02 披露方案', '03 风险与审批', '04 摘要与回链'].entries()) {
      await page.getByRole('button', { name: stage, exact: true }).click();
      await expect(page.getByLabel('本案阶段内容')).toContainText(expected[index].stages[stageIndex]);
    }
    await page.getByRole('button', { name: '01 材料与事实', exact: true }).click();

    const runTool = async (button: string, token: string) => {
      const created = page.waitForResponse(response => response.url().includes('/cases/') && response.url().endsWith('/tasks'));
      await page.getByRole('button', { name: button, exact: true }).click();
      expect((await created).status()).toBe(200);
      await expect(page.locator('.work-panel')).toContainText(token);
      await expect(page.locator('.work-panel').getByRole('link', { name: '导出结果' })).toBeVisible();
      await expect(page.locator('.work-panel').getByRole('button', { name: '回到原文' }).first()).toBeVisible();
      await page.getByRole('button', { name: '01 材料与事实', exact: true }).click();
    };

    await runTool('本地生成时间线', expected[index].timeline);
    await runTool('本地整理证据清单', expected[index].evidence);
    await runTool('本地生成争点候选', expected[index].issue);
  }
});
