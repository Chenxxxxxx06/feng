import { expect, test, type Page } from '@playwright/test';


async function login(page: Page) {
  await page.goto('/login');
  await page.evaluate(() => localStorage.setItem('app.onboarding.v1.done', '1'));
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}


test('登录页保持旧版紧凑布局并完成真实登录', async ({ page }) => {
  await page.goto('/login');

  const panel = page.locator('.ops-panel').first();
  await expect(panel).toBeVisible();
  const box = await panel.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(360);
  expect(box!.width).toBeLessThanOrEqual(385);
  await expect(page.getByPlaceholder('用户名')).toBeVisible();
  await expect(page.getByPlaceholder('密码')).toBeVisible();

  await login(page);
});


test('Dashboard 四个工作区高度稳定且 SCADA 图表可见', async ({ page }) => {
  await login(page);

  const panels = [
    page.getByRole('region', { name: '风机健康监测' }),
    page.getByRole('region', { name: '告警中心' }).locator('..'),
    page.getByRole('region', { name: 'SCADA 数据趋势' }),
    page.getByRole('region', { name: 'AI 全场摘要' }),
  ];
  const heights: number[] = [];
  for (const panel of panels) {
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    heights.push(Math.round(box!.height));
  }
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(2);
  expect(heights[0]).toBe(360);

  const scadaPanel = page.getByRole('region', { name: 'SCADA 数据趋势' });
  await expect(scadaPanel.locator('canvas')).toHaveCount(3);
  await expect(page.getByRole('button', { name: '打开风调 AI 助手' })).toHaveCount(1);
});


test('所有工作区均保留唯一 AI 助手入口', async ({ page }) => {
  await login(page);

  for (const path of [
    '/dashboard',
    '/incident',
    '/diagnosis',
    '/drone-scheduler',
    '/knowledge',
    '/prediction',
    '/workorder',
    '/settings',
    '/turbine/1',
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole('button', { name: '打开风调 AI 助手' }),
      `assistant count mismatch on ${path}`,
    ).toHaveCount(1);
  }
});


test('核心闭环页面完成业务归位并可正常展示', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);

  await page.goto('/prediction');
  const forecastPanel = page.getByRole('region', { name: '未来七天风功率预测' });
  await expect(forecastPanel).toBeVisible();
  await expect(forecastPanel.getByText('加载风功率预测...', { exact: true })).toHaveCount(0, { timeout: 30000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: 'test-results/v14-prediction.png' });

  await page.goto('/workorder');
  const schedulePanel = page.getByRole('region', { name: '维护窗口与方案' });
  await expect(schedulePanel).toBeVisible();
  await expect(schedulePanel.getByText('加载维护窗口...', { exact: true })).toHaveCount(0, { timeout: 30000 });
  await expect(page.getByText('维修工单工作台')).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: 'test-results/v14-workorder.png' });

  await page.goto('/incident');
  await expect(page.getByText('跨模块异常处置工作台', { exact: false })).toBeVisible();
  await page.getByLabel('事件列表').getByRole('button').filter({ hasNotText: /新建|收起/ }).first().click();
  await expect(page.getByLabel('事件处置闭环')).toBeVisible();
  await expect(page.getByRole('link', { name: '进入维修工单' })).toBeVisible();
  await expect(page.getByRole('button', { name: '打开风调 AI 助手' })).toHaveCount(1);
  await page.waitForTimeout(800);
  await page.screenshot({ path: 'test-results/v14-incident.png' });
});
