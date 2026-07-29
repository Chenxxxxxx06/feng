import { expect, test, type Page } from '@playwright/test';


async function login(page: Page) {
  await page.goto('/login');
  await page.evaluate(() => localStorage.setItem('app.onboarding.v1.done', '1'));
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}


test('单风机详情使用有界数据并快速完成四个监控面板', async ({ page }) => {
  await login(page);

  const turbineId = await page.evaluate(async () => {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/turbines/?page_size=1', {
      headers: { Authorization: `Bearer ${token}` },
    });
    const payload = await response.json();
    return payload.turbines[0].id as number;
  });

  const scadaResponse = page.waitForResponse(
    (response) => response.url().includes(`/turbines/${turbineId}/scada?`)
      && response.status() === 200,
  );
  const vibrationResponse = page.waitForResponse(
    (response) => response.url().includes('/diagnosis/vibration?')
      && response.status() === 200,
  );
  const aiResponse = page.waitForResponse(
    (response) => response.url().endsWith('/api/ai/summary')
      && response.status() === 200,
  );

  const navigationStarted = Date.now();
  await page.goto(`/turbine/${turbineId}`);

  const [scada, vibration, ai] = await Promise.all([
    (await scadaResponse).json(),
    (await vibrationResponse).json(),
    (await aiResponse).json(),
  ]);

  expect(scada.length).toBeLessThanOrEqual(144);
  expect(vibration.waveform.length).toBeLessThanOrEqual(1024);
  expect(ai.conclusions.length).toBeGreaterThan(0);

  await expect(page.getByRole('heading', { name: /SCADA (历史数据窗口|运行数据曲线)/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: '环境监控' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /振动波形/ })).toContainText('RMS:');
  await expect(page.getByRole('heading', { name: '🤖 AI 智能诊断总结' })).toBeVisible();
  await expect(page.getByText('AI 正在分析该风机数据...', { exact: true })).toHaveCount(0);

  // The panel must become useful before a slow external weather refresh can
  // block it; SCADA-derived environment values provide that first paint.
  expect(Date.now() - navigationStarted).toBeLessThan(5_000);
});
