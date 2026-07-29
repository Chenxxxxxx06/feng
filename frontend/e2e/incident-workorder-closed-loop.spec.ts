import { expect, test, type Page } from '@playwright/test';


async function loginAsAdmin(page: Page) {
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.setItem('app.onboarding.v1.done', '1');
    sessionStorage.setItem('app.desktopDigest.shownThisSession', 'true');
  });
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const closeSummary = page.getByRole('button', { name: '关闭桌面摘要' });
  if (await closeSummary.isVisible().catch(() => false)) await closeSummary.click();
}

async function advanceWorkOrder(page: Page, card: ReturnType<Page['locator']>, label: string) {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/workorders/')
      && response.request().method() === 'PUT',
  );
  await card.getByRole('button', { name: label, exact: true }).click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
}


test('事件关联工单创建后可完成恢复验证并关闭事件', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginAsAdmin(page);
  await page.goto('/incident');

  const prepareResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/competition-demo/prepare') &&
      response.request().method() === 'POST',
  );
  await page.getByTestId('prepare-competition-demo').click();
  const prepareResponse = await prepareResponsePromise;
  expect(prepareResponse.ok()).toBeTruthy();
  const prepared = await prepareResponse.json();
  const incidentId = Number(prepared.incident_id);
  expect(incidentId).toBeGreaterThan(0);

  await expect(page.getByText('评审演示场景已重置')).toBeVisible();
  await expect(
    page.getByLabel('事件列表').getByText('INC-DEMO-YJ-A-013', { exact: true }),
  ).toBeVisible();

  await page.getByTestId('incident-create-workorder').click();
  await expect(page).toHaveURL(new RegExp(`/workorder\\?.*incident_id=${incidentId}`));
  await expect(page.getByTestId('incident-workorder-context')).toContainText('INC-DEMO-YJ-A-013');
  await expect(page.getByLabel('选择风机')).toBeDisabled();

  const workorderTitle = `E2E-闭环关联-${Date.now()}`;
  await page.getByPlaceholder('工单标题 *').fill(workorderTitle);

  const createResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes('/api/workorders/') &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '创建', exact: true }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = await createResponse.json();
  expect(created.incident_id).toBe(incidentId);
  expect(created.turbine_id).toBe(Number(prepared.turbine_id));
  const token = await page.evaluate(() => localStorage.getItem('token'));

  try {
    const createdCard = page.locator(`article[data-wo-id="${created.id}"]`);
    await expect(createdCard).toBeVisible();
    await expect(createdCard).toContainText(workorderTitle);
    await expect(createdCard).toContainText(`INC #${incidentId}`);

    // Advance the exact order created above through the real UI state machine.
    await advanceWorkOrder(page, createdCard, '推进到已分配');
    await expect(createdCard).toContainText('已分配');
    await advanceWorkOrder(page, createdCard, '推进到执行中');
    await expect(createdCard).toContainText('执行中');
    await advanceWorkOrder(page, createdCard, '推进到待验收');
    await expect(createdCard).toContainText('待验收');
    await advanceWorkOrder(page, createdCard, '推进到已完成');
    await expect(createdCard).toContainText('已完成');

    await page.goto('/incident');
    const demoIncident = page
      .getByLabel('事件列表')
      .getByRole('button')
      .filter({ hasText: 'INC-DEMO-YJ-A-013' });
    await demoIncident.click();

    // Replay is strictly scoped to the labelled demo and builds a 25-hour
    // post-maintenance observation window for this exact newly created order.
    const replayResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/competition-demo/incidents/${incidentId}/time-replay`)
        && response.request().method() === 'POST',
    );
    await page.getByTestId('demo-time-replay').click();
    const replayResponse = await replayResponsePromise;
    expect(replayResponse.ok()).toBeTruthy();
    const replay = await replayResponse.json();
    expect(replay.work_order_id).toBe(created.id);
    expect(replay.simulated_elapsed_hours).toBeGreaterThanOrEqual(24);

    const verifyResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/incidents/${incidentId}/verify-recovery`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '恢复验证', exact: true }).click();
    const verifyResponse = await verifyResponsePromise;
    expect(verifyResponse.ok()).toBeTruthy();
    const certificate = await verifyResponse.json();
    expect(certificate.verification_status).toBe('pass');

    await expect(page.getByText('验证通过', { exact: true }).first()).toBeVisible();
    const resolveResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/api/incidents/${incidentId}/transition`) &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '标记解决', exact: true }).click();
    const resolveResponse = await resolveResponsePromise;
    expect(resolveResponse.ok()).toBeTruthy();
    const resolved = await resolveResponse.json();
    expect(resolved.stage).toBe('resolved');
    expect(resolved.status).toBe('resolved');
    expect(resolved.verification_status).toBe('pass');

    await expect(page.getByLabel('事件处置闭环')).toContainText('已完成处置闭环');
  } finally {
    if (token && created?.id && !page.isClosed()) {
      await page.request
        .delete(`/api/workorders/${created.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .catch(() => {});
    }
  }
});
