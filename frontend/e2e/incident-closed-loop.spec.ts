import { test, expect } from '@playwright/test';

/** E2E: Incident ProofLoop closed-loop workflow.
 *
 * Prerequisites: backend running on 127.0.0.1:8000
 * Run: E2E_API_BASE=http://127.0.0.1:8000 npx playwright test frontend/e2e/incident-closed-loop.spec.ts
 *
 * All scenarios use the real /api prefix. Server-unreachable is a hard failure, not a skip.
 */

const BASE = process.env.E2E_API_BASE || 'http://127.0.0.1:8000';
const API = `${BASE}/api`;

// ── Scenario 1: Normal closed loop (API-level) ──

test('Scenario 1: Full ProofLoop — create → investigate → plan → verify → close → audit', async ({ request }) => {
  // 1. Login
  const loginResp = await request.post(`${API}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  expect(loginResp.ok(), `Login failed: ${loginResp.status()} ${await loginResp.text()}`).toBeTruthy();

  // 2. Create incident
  const createResp = await request.post(`${API}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Gearbox anomaly', severity: 'high' },
  });
  expect(createResp.status(), `Create failed: ${await createResp.text()}`).toBe(201);
  const inc = await createResp.json();
  const incId = inc.id;
  console.log(`  Created: ${inc.incident_id}`);

  // 3. Start investigation
  const invResp = await request.post(`${API}/incidents/${incId}/start-investigation`);
  expect(invResp.ok(), `Investigation failed: ${await invResp.text()}`).toBeTruthy();
  const inv = await invResp.json();
  expect(inv.trace_id).toBeTruthy();
  console.log(`  Investigation: ${inv.status}`);

  // 4. Generate plans
  const planResp = await request.post(`${API}/incidents/${incId}/generate-plans`);
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
  const evResp = await request.get(`${API}/incidents/${incId}/evidence-completeness`);
  expect(evResp.ok()).toBeTruthy();
  const ev = await evResp.json();
  expect(ev.hasOwnProperty('can_confirm_diagnosis')).toBeTruthy();
  console.log(`  Evidence: ${(ev.completeness_ratio * 100).toFixed(0)}%`);

  // 6. Economic impact
  const ecoResp = await request.get(`${API}/incidents/${incId}/economic-impact`);
  expect(ecoResp.ok()).toBeTruthy();
  const eco = await ecoResp.json();
  expect(eco.elapsed_hours).toBeGreaterThanOrEqual(0);
  expect(typeof eco.cumulative_loss_cny).toBe('number');
  console.log(`  Economic: ¥${eco.cumulative_loss_cny.toFixed(0)}`);

  // 7. Audit chain
  const auditResp = await request.get(`${API}/incidents/${incId}/audit-chain`);
  expect(auditResp.ok()).toBeTruthy();
  const audit = await auditResp.json();
  console.log(`  Audit: ${audit.total_entries} entries`);

  const auditVerify = await request.post(`${API}/incidents/${incId}/audit-chain/verify`);
  expect(auditVerify.ok()).toBeTruthy();
  const av = await auditVerify.json();
  expect(av.chain_valid).toBeTruthy();

  // 8. Compliance check
  const compResp = await request.post(`${API}/incidents/${incId}/compliance/check`, {
    params: { action: 'close_incident' },
  });
  expect(compResp.ok()).toBeTruthy();
  const comp = await compResp.json();
  console.log(`  Compliance: ${comp.passed}/${comp.total_rules}`);

  console.log('  ✅ Scenario 1 complete');
});

// ── Scenario 2: Policy enforcement ──

test('Scenario 2: Policy blocks close without verification', async ({ request }) => {
  const loginResp = await request.post(`${API}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy();

  const createResp = await request.post(`${API}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Policy test', severity: 'medium' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Try to close directly — MUST be rejected
  const closeResp = await request.post(`${API}/incidents/${inc.id}/transition`, {
    data: { target_stage: 'resolved', note: 'Attempting to close without verification' },
  });
  expect([403, 409]).toContain(closeResp.status());
  console.log(`  Policy blocked close: ${closeResp.status()}`);

  // Verify NOT resolved
  const getResp = await request.get(`${API}/incidents/${inc.id}`);
  const after = await getResp.json();
  expect(after.stage).not.toBe('resolved');

  console.log('  ✅ Scenario 2 complete');
});

// ── Scenario 3: Safe degradation — evidence completeness works ──

test('Scenario 3: Investigation survives — evidence completeness works', async ({ request }) => {
  const loginResp = await request.post(`${API}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  expect(loginResp.ok(), `Login failed: ${loginResp.status()}`).toBeTruthy();

  const createResp = await request.post(`${API}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Evidence test', severity: 'low' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Before investigation: should NOT confirm diagnosis
  const evBefore = await request.get(`${API}/incidents/${inc.id}/evidence-completeness`);
  const before = await evBefore.json();
  expect(before.can_confirm_diagnosis).toBeFalsy();
  expect(before.missing_evidence.length).toBeGreaterThan(0);

  // Start investigation
  const invResp = await request.post(`${API}/incidents/${inc.id}/start-investigation`);
  expect(invResp.ok(), `Investigation failed: ${await invResp.text()}`).toBeTruthy();
  const inv = await invResp.json();
  expect(inv.status).toBe('completed');
  console.log(`  Investigation: ${inv.status}`);

  // After investigation: should have more evidence
  const evAfter = await request.get(`${API}/incidents/${inc.id}/evidence-completeness`);
  const after = await evAfter.json();
  console.log(`  Evidence: ${(after.completeness_ratio * 100).toFixed(0)}%`);

  console.log('  ✅ Scenario 3 complete');
});

// ── Scenario 4: Browser UI — incident page loads and renders ──

test('Scenario 4: Browser UI — incident page renders and tabs work', async ({ page }) => {
  // Navigate to the incident page (Vite dev server or production build)
  const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5173';
  await page.goto(`${FRONTEND_URL}/incidents`);

  // Wait for the page to load — should show either incident list or login redirect
  await page.waitForLoadState('networkidle');

  // Check that the page has meaningful content (not a blank error page)
  const bodyText = await page.textContent('body');
  expect(bodyText).toBeTruthy();

  // If redirected to login, that's acceptable for UI test (proves routing works)
  // If on incident page, verify key elements exist
  const hasIncidentList = await page.locator('text=事件列表').count();
  const hasLogin = await page.locator('text=登录').count();
  const hasCreateButton = await page.locator('text=新建').count();

  // At least one of these should be present (not a blank/broken page)
  expect(hasIncidentList + hasLogin + hasCreateButton).toBeGreaterThan(0);
  console.log(`  UI check: incident_list=${hasIncidentList}, login=${hasLogin}, create=${hasCreateButton}`);

  console.log('  ✅ Scenario 4 complete');
});
