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


test('只读角色在浏览器中看不到可执行写操作且后端拒绝越权', async ({ page }) => {
  const suffix = `${Date.now()}-${test.info().retry}`;
  const register = await page.request.post('/api/auth/register', {
    data: {
      username: `viewer_e2e_${suffix}`,
      email: `viewer-e2e-${suffix}@example.com`,
      password: 'viewer-pass-123',
      role: 'admin',
    },
  });
  expect(register.ok()).toBeTruthy();
  const auth = await register.json();
  expect(auth.user.role).toBe('viewer');

  await page.addInitScript(({ token, user }) => {
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify(user));
    localStorage.setItem('app.onboarding.v1.done', '1');
    sessionStorage.setItem('app.desktopDigest.shownThisSession', 'true');
  }, { token: auth.access_token, user: auth.user });

  await page.goto('/workorder');
  const createWorkOrder = page.locator('[data-action="create-workorder"]');
  await expect(createWorkOrder).toBeDisabled();
  await expect(createWorkOrder).toHaveAttribute('title', /只读角色/);

  await page.goto('/incident');
  const createIncident = page.getByRole('button', { name: '+ 新建', exact: true });
  await expect(createIncident).toBeDisabled();
  await expect(createIncident).toHaveAttribute('title', /只读角色/);

  const forbidden = await page.request.post('/api/competition-demo/prepare', {
    headers: { Authorization: `Bearer ${auth.access_token}` },
  });
  expect(forbidden.status()).toBe(403);
});


test('Agent 在真实浏览器会话中规划、确认并回读事件关联工单', async ({ page }) => {
  await loginAsAdmin(page);
  const token = await page.evaluate(() => localStorage.getItem('token'));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };

  const preparedResponse = await page.request.post('/api/competition-demo/prepare', { headers });
  expect(preparedResponse.ok()).toBeTruthy();
  const prepared = await preparedResponse.json();
  const incidentResponse = await page.request.get(`/api/incidents/${prepared.incident_id}`, { headers });
  expect(incidentResponse.ok()).toBeTruthy();
  const incident = await incidentResponse.json();

  const planResponse = await page.request.post('/api/agent-actions/plan', {
    headers,
    data: {
      message: '为当前事件创建维修工单',
      page_context: {
        page_type: 'incident',
        incident_id: incident.id,
        incident_ref: incident.incident_id,
        turbine_id: incident.turbine_id,
        turbine_name: incident.turbine_name,
      },
    },
  });
  const planText = await planResponse.text();
  expect(planResponse.ok(), `Agent plan failed: ${planResponse.status()} ${planText}`).toBeTruthy();
  const plan = JSON.parse(planText);
  expect(plan.status).toBe('pending_confirmation');
  expect(plan.confirmation.after.incident_id).toBe(incident.id);

  const confirmResponse = await page.request.post(
    `/api/agent-actions/${plan.request_id}/confirm`,
    { headers },
  );
  expect(confirmResponse.ok()).toBeTruthy();
  const confirmed = await confirmResponse.json();
  expect(confirmed.status).toBe('success');

  try {
    const readBackResponse = await page.request.get('/api/workorders/', { headers });
    expect(readBackResponse.ok()).toBeTruthy();
    const readBack = (await readBackResponse.json()).find(
      (item: { id: number }) => item.id === confirmed.result.id,
    );
    expect(readBack).toBeTruthy();
    expect(readBack.incident_id).toBe(incident.id);

    await page.goto('/workorder');
    const card = page.locator(`article[data-wo-id="${confirmed.result.id}"]`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(`INC #${incident.id}`);
  } finally {
    await page.request.delete(`/api/workorders/${confirmed.result.id}`, { headers }).catch(() => {});
  }
});
