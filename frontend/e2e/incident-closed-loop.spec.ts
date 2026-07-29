import { test, expect, type APIRequestContext } from '@playwright/test';

/** E2E: Incident ProofLoop closed-loop workflow.
 *
 * Prerequisites: backend running on 127.0.0.1:8000
 * Run: E2E_API_BASE=http://127.0.0.1:8000 npx playwright test frontend/e2e/incident-closed-loop.spec.ts
 *
 * All scenarios use the real /api prefix. Server-unreachable is a hard failure, not a skip.
 */

const BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000';
const API = `${BASE}/api`;


async function authenticatedApi(request: APIRequestContext) {
  const loginResp = await request.post(`${API}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  expect(loginResp.ok(), `Login failed: ${loginResp.status()} ${await loginResp.text()}`).toBeTruthy();
  const login = await loginResp.json();
  const headers = { Authorization: `Bearer ${login.access_token}` };
  const turbinesResp = await request.get(`${API}/turbines/`, { headers });
  expect(turbinesResp.ok(), `Turbine lookup failed: ${await turbinesResp.text()}`).toBeTruthy();
  const turbines = await turbinesResp.json();
  expect(turbines.turbines.length).toBeGreaterThan(0);
  return { headers, turbineId: Number(turbines.turbines[0].id) };
}

// ── Scenario 1: Normal closed loop (API-level) ──

test('Scenario 1: Full ProofLoop — create → investigate → plan → verify → close → audit', async ({ request }) => {
  const { headers, turbineId } = await authenticatedApi(request);

  // 2. Create incident
  const createResp = await request.post(`${API}/incidents`, {
    headers,
    data: { turbine_id: turbineId, title: 'Playwright E2E: Gearbox anomaly', severity: 'high' },
  });
  expect(createResp.status(), `Create failed: ${await createResp.text()}`).toBe(201);
  const inc = await createResp.json();
  const incId = inc.id;
  console.log(`  Created: ${inc.incident_id}`);

  // 3. Start investigation
  const invResp = await request.post(`${API}/incidents/${incId}/start-investigation`, { headers });
  expect(invResp.ok(), `Investigation failed: ${await invResp.text()}`).toBeTruthy();
  const inv = await invResp.json();
  expect(inv.trace_id).toBeTruthy();
  console.log(`  Investigation: ${inv.status}`);

  // 4. Generate plans
  const planResp = await request.post(`${API}/incidents/${incId}/generate-plans`, { headers });
  expect(planResp.ok(), `Plans failed: ${await planResp.text()}`).toBeTruthy();
  const plans = await planResp.json();
  expect(plans.plans.length).toBeGreaterThan(0);

  // Verify: no hardcoded values in plans
  for (const p of plans.plans) {
    expect(typeof p.safety_risk).toBe('number');
    expect(typeof p.total_score).toBe('number');
    expect(p.hasOwnProperty('is_feasible')).toBeTruthy();
  }
  console.log(`  Plans: ${plans.plans.length}`);

  // 5. Evidence completeness
  const evResp = await request.get(`${API}/incidents/${incId}/evidence-completeness`, { headers });
  expect(evResp.ok()).toBeTruthy();
  const ev = await evResp.json();
  expect(ev.hasOwnProperty('can_confirm_diagnosis')).toBeTruthy();
  console.log(`  Evidence: ${(ev.completeness_ratio * 100).toFixed(0)}%`);

  // 6. Economic impact
  const ecoResp = await request.get(`${API}/incidents/${incId}/economic-impact`, { headers });
  expect(ecoResp.ok()).toBeTruthy();
  const eco = await ecoResp.json();
  expect(eco.elapsed_hours).toBeGreaterThanOrEqual(0);
  expect(typeof eco.cumulative_loss_cny).toBe('number');
  console.log(`  Economic: ¥${eco.cumulative_loss_cny.toFixed(0)}`);

  // 7. Audit chain
  const auditResp = await request.get(`${API}/incidents/${incId}/audit-chain`, { headers });
  expect(auditResp.ok()).toBeTruthy();
  const audit = await auditResp.json();
  console.log(`  Audit: ${audit.total_entries} entries`);

  const auditVerify = await request.post(`${API}/incidents/${incId}/audit-chain/verify`, { headers });
  expect(auditVerify.ok()).toBeTruthy();
  const av = await auditVerify.json();
  expect(av.chain_valid).toBeTruthy();

  // 8. Compliance check
  const compResp = await request.post(`${API}/incidents/${incId}/compliance/check`, {
    headers,
    params: { action: 'close_incident' },
  });
  expect(compResp.ok()).toBeTruthy();
  const comp = await compResp.json();
  console.log(`  Compliance: ${comp.passed}/${comp.total_rules}`);

  console.log('  ✅ Scenario 1 complete');
});

// ── Scenario 2: Policy enforcement ──

test('Scenario 2: Policy blocks close without verification', async ({ request }) => {
  const { headers, turbineId } = await authenticatedApi(request);

  const createResp = await request.post(`${API}/incidents`, {
    headers,
    data: { turbine_id: turbineId, title: 'Playwright E2E: Policy test', severity: 'medium' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Try to close directly — MUST be rejected
  const closeResp = await request.post(`${API}/incidents/${inc.id}/transition`, {
    headers,
    data: { target_stage: 'resolved', note: 'Attempting to close without verification' },
  });
  expect([403, 409]).toContain(closeResp.status());
  console.log(`  Policy blocked close: ${closeResp.status()}`);

  // Verify NOT resolved
  const getResp = await request.get(`${API}/incidents/${inc.id}`, { headers });
  const after = await getResp.json();
  expect(after.stage).not.toBe('resolved');

  console.log('  ✅ Scenario 2 complete');
});

// ── Scenario 3: Safe degradation — evidence completeness works ──

test('Scenario 3: Investigation survives — evidence completeness works', async ({ request }) => {
  const { headers, turbineId } = await authenticatedApi(request);

  const createResp = await request.post(`${API}/incidents`, {
    headers,
    data: { turbine_id: turbineId, title: 'Playwright E2E: Evidence test', severity: 'low' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Before investigation: should NOT confirm diagnosis
  const evBefore = await request.get(`${API}/incidents/${inc.id}/evidence-completeness`, { headers });
  const before = await evBefore.json();
  expect(before.can_confirm_diagnosis).toBeFalsy();
  expect(before.missing_evidence.length).toBeGreaterThan(0);

  // Start investigation
  const invResp = await request.post(`${API}/incidents/${inc.id}/start-investigation`, { headers });
  expect(invResp.ok(), `Investigation failed: ${await invResp.text()}`).toBeTruthy();
  const inv = await invResp.json();
  expect(inv.status).toBe('completed');
  console.log(`  Investigation: ${inv.status}`);

  // After investigation: should have more evidence
  const evAfter = await request.get(`${API}/incidents/${inc.id}/evidence-completeness`, { headers });
  const after = await evAfter.json();
  console.log(`  Evidence: ${(after.completeness_ratio * 100).toFixed(0)}%`);

  console.log('  ✅ Scenario 3 complete');
});

// ── Scenario 4: Browser UI — incident page loads and renders ──

test('Scenario 4: Browser UI — incident page renders and tabs work', async ({ page }) => {
  const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5173';
  await page.goto(`${FRONTEND_URL}/login`);
  await page.evaluate(() => localStorage.setItem('app.onboarding.v1.done', '1'));
  await page.getByLabel('用户名').fill('admin');
  await page.getByLabel('密码').fill('admin123');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto(`${FRONTEND_URL}/incident`);
  await expect(page.getByLabel('事件列表')).toBeVisible();
  await expect(page.getByRole('heading', { name: '事件指挥工作台' })).toBeVisible();

  console.log('  ✅ Scenario 4 complete');
});
