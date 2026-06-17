import api from './api';

export const PREFERENCES_UPDATED_EVENT = 'preferences-updated';

export interface UserPreferences {
  displayName: string;
  email: string;
  phone: string;
  region: string;
  landingPage: string;
  digestFrequency: 'realtime' | 'daily' | 'weekly' | 'off';
  desktopDigest: boolean;
  compactWorkspace: boolean;
  riskFirst: boolean;
  autoOpenCopilot: boolean;
}

const STORAGE_KEY = 'app.userPreferences.v1';
const DIGEST_LAST_SHOWN_KEY = 'app.desktopDigest.lastShownAt';
const DIGEST_SESSION_KEY = 'app.desktopDigest.shownThisSession';
const LEGACY_LANDING_KEY = 'landingPage';
const LEGACY_COPILOT_KEY = 'autoOpenCopilot';

const LANDING_PAGES = new Set(['dashboard', 'diagnosis', 'prediction', 'workorder']);
const DIGEST_FREQUENCIES = new Set(['realtime', 'daily', 'weekly', 'off']);

export const DEFAULT_PREFERENCES: UserPreferences = {
  displayName: '',
  email: '',
  phone: '',
  region: '陕北',
  landingPage: 'dashboard',
  digestFrequency: 'daily',
  desktopDigest: true,
  compactWorkspace: false,
  riskFirst: true,
  autoOpenCopilot: false,
};

const safeWindow = () => (typeof window === 'undefined' ? null : window);

export function normalizePreferences(raw?: Partial<UserPreferences> | null): UserPreferences {
  const legacyLanding = safeWindow()?.localStorage.getItem(LEGACY_LANDING_KEY) || undefined;
  const legacyCopilot = safeWindow()?.localStorage.getItem(LEGACY_COPILOT_KEY);
  const next = { ...DEFAULT_PREFERENCES, ...(raw || {}) };
  next.landingPage = LANDING_PAGES.has(next.landingPage) ? next.landingPage : legacyLanding || DEFAULT_PREFERENCES.landingPage;
  if (!LANDING_PAGES.has(next.landingPage)) next.landingPage = DEFAULT_PREFERENCES.landingPage;
  next.digestFrequency = DIGEST_FREQUENCIES.has(next.digestFrequency)
    ? next.digestFrequency
    : DEFAULT_PREFERENCES.digestFrequency;
  if (raw?.autoOpenCopilot == null && legacyCopilot != null) {
    next.autoOpenCopilot = legacyCopilot === 'true';
  }
  return next;
}

export function loadLocalPreferences(): UserPreferences {
  const win = safeWindow();
  if (!win) return DEFAULT_PREFERENCES;
  try {
    const parsed = JSON.parse(win.localStorage.getItem(STORAGE_KEY) || '{}') as Partial<UserPreferences>;
    return normalizePreferences(parsed);
  } catch {
    return normalizePreferences(null);
  }
}

export function applyPreferences(prefs: UserPreferences) {
  const win = safeWindow();
  if (!win) return;
  win.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  win.localStorage.setItem(LEGACY_LANDING_KEY, prefs.landingPage);
  win.localStorage.setItem(LEGACY_COPILOT_KEY, String(prefs.autoOpenCopilot));
  win.document.body.classList.toggle('compact-workspace', prefs.compactWorkspace);
  win.dispatchEvent(new CustomEvent(PREFERENCES_UPDATED_EVENT, { detail: prefs }));
}

export async function fetchUserPreferences(): Promise<UserPreferences> {
  const { data } = await api.get('/settings/preferences');
  const prefs = normalizePreferences(data);
  applyPreferences(prefs);
  return prefs;
}

export async function saveUserPreferences(payload: Partial<UserPreferences>): Promise<UserPreferences> {
  const prefs = normalizePreferences(payload);
  await api.put('/settings/preferences', prefs);
  applyPreferences(prefs);
  return prefs;
}

export function canShowDesktopDigest(prefs: UserPreferences): boolean {
  const win = safeWindow();
  if (!win || !prefs.desktopDigest || prefs.digestFrequency === 'off') return false;
  if (win.sessionStorage.getItem(DIGEST_SESSION_KEY) === 'true') return false;
  if (prefs.digestFrequency === 'realtime') return true;
  const lastShown = Date.parse(win.localStorage.getItem(DIGEST_LAST_SHOWN_KEY) || '');
  if (!Number.isFinite(lastShown)) return true;
  const elapsed = Date.now() - lastShown;
  if (prefs.digestFrequency === 'daily') return elapsed >= 24 * 60 * 60 * 1000;
  if (prefs.digestFrequency === 'weekly') return elapsed >= 7 * 24 * 60 * 60 * 1000;
  return false;
}

export function markDesktopDigestShown() {
  const win = safeWindow();
  if (!win) return;
  win.sessionStorage.setItem(DIGEST_SESSION_KEY, 'true');
  win.localStorage.setItem(DIGEST_LAST_SHOWN_KEY, new Date().toISOString());
}
