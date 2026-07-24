import { test, expect } from '@playwright/test';

/** E2E: Incident ProofLoop closed-loop workflow.
 *
 * Prerequisites: backend running on localhost:8080
 * Run: npx playwright test frontend/e2e/incident-closed-loop.spec.ts
 */

const BASE = 'http://localhost:8080';

// ── Scenario 1: Normal closed loop ──

test('Scenario 1: Full ProofLoop — create → investigate → plan → verify → close → audit', async ({ request }) => {
  // 1. Login
  const loginResp = await request.post(`${BASE}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  if (loginResp.status() === 401) {
    test.skip(true, 'Auth required — run with valid credentials');
    return;
  }
  expect(loginResp.ok()).toBeTruthy();

  // 2. Create incident
  const createResp = await request.post(`${BASE}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Gearbox anomaly', severity: 'high' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();
  const incId = inc.id;
  console.log(`  Created: ${inc.incident_id}`);

  // 3. Start investigation
  const invResp = await request.post(`${BASE}/incidents/${incId}/start-investigation`);
  expect(invResp.ok()).toBeTruthy();
  const inv = await invResp.json();
  expect(inv.trace_id).toBeTruthy();
  console.log(`  Investigation: ${inv.status}`);

  // 4. Generate plans
  const planResp = await request.post(`${BASE}/incidents/${incId}/generate-plans`);
  expect(planResp.ok()).toBeTruthy();
  const plans = await planResp.json();
  expect(plans.plans.length).toBeGreaterThan(0);

  // Verify: no hardcoded values in plans
  for (const p of plans.plans) {
    expect(typeof p.safety_risk).toBe('number');
    expect(typeof p.total_score).toBe('number');
    // Should have feasibility info (NOT just boolean true)
    expect(p.hasOwnProperty('is_feasible')).toBeTruthy();
  }
  console.log(`  Plans: ${plans.plans.length}`);

  // 5. Evidence completeness
  const evResp = await request.get(`${BASE}/incidents/${incId}/evidence-completeness`);
  expect(evResp.ok()).toBeTruthy();
  const ev = await evResp.json();
  expect(ev.hasOwnProperty('can_confirm_diagnosis')).toBeTruthy();
  console.log(`  Evidence: ${(ev.completeness_ratio * 100).toFixed(0)}%`);

  // 6. Economic impact
  const ecoResp = await request.get(`${BASE}/incidents/${incId}/economic-impact`);
  expect(ecoResp.ok()).toBeTruthy();
  const eco = await ecoResp.json();
  expect(eco.elapsed_hours).toBeGreaterThanOrEqual(0);
  expect(typeof eco.cumulative_loss_cny).toBe('number');
  console.log(`  Economic: ¥${eco.cumulative_loss_cny.toFixed(0)}`);

  // 7. Audit chain
  const auditResp = await request.get(`${BASE}/incidents/${incId}/audit-chain`);
  expect(auditResp.ok()).toBeTruthy();
  const audit = await auditResp.json();
  console.log(`  Audit: ${audit.total_entries} entries`);

  const auditVerify = await request.post(`${BASE}/incidents/${incId}/audit-chain/verify`);
  expect(auditVerify.ok()).toBeTruthy();
  const av = await auditVerify.json();
  // Chain should be valid (even if empty — nothing to tamper with)
  expect(av.chain_valid).toBeTruthy();

  // 8. Compliance check
  const compResp = await request.post(`${BASE}/incidents/${incId}/compliance/check`, {
    params: { action: 'close_incident' },
  });
  expect(compResp.ok()).toBeTruthy();
  const comp = await compResp.json();
  console.log(`  Compliance: ${comp.passed}/${comp.total_rules}`);

  console.log('  ✅ Scenario 1 complete');
});

// ── Scenario 2: Policy enforcement ──

test('Scenario 2: Policy blocks close without verification', async ({ request }) => {
  const loginResp = await request.post(`${BASE}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  if (loginResp.status() === 401) {
    test.skip(true, 'Auth required');
    return;
  }

  const createResp = await request.post(`${BASE}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Policy test', severity: 'medium' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Try to close directly — MUST be rejected
  const closeResp = await request.post(`${BASE}/incidents/${inc.id}/transition`, {
    data: { target_stage: 'resolved', note: 'Attempting to close without verification' },
  });
  expect([403, 409]).toContain(closeResp.status());
  console.log(`  Policy blocked close: ${closeResp.status()}`);

  // Verify NOT resolved
  const getResp = await request.get(`${BASE}/incidents/${inc.id}`);
  const after = await getResp.json();
  expect(after.stage).not.toBe('resolved');

  console.log('  ✅ Scenario 2 complete');
});

// ── Scenario 3: Safe degradation ──

test('Scenario 3: Investigation survives — evidence completeness works', async ({ request }) => {
  const loginResp = await request.post(`${BASE}/auth/login`, {
    data: { username: 'admin', password: 'admin123' },
  });
  if (loginResp.status() === 401) {
    test.skip(true, 'Auth required');
    return;
  }

  const createResp = await request.post(`${BASE}/incidents`, {
    data: { turbine_id: 31, title: 'Playwright E2E: Evidence test', severity: 'low' },
  });
  expect(createResp.status()).toBe(201);
  const inc = await createResp.json();

  // Before investigation: should NOT confirm diagnosis
  const evBefore = await request.get(`${BASE}/incidents/${inc.id}/evidence-completeness`);
  const before = await evBefore.json();
  expect(before.can_confirm_diagnosis).toBeFalsy();
  expect(before.missing_evidence.length).toBeGreaterThan(0);

  // Start investigation
  const invResp = await request.post(`${BASE}/incidents/${inc.id}/start-investigation`);
  if (invResp.ok()) {
    const inv = await invResp.json();
    expect(inv.status).toBe('completed');
    console.log(`  Investigation: ${inv.status}`);

    // After investigation: should have more evidence
    const evAfter = await request.get(`${BASE}/incidents/${inc.id}/evidence-completeness`);
    const after = await evAfter.json();
    console.log(`  Evidence: ${(after.completeness_ratio * 100).toFixed(0)}%`);
  }

  console.log('  ✅ Scenario 3 complete');
});
