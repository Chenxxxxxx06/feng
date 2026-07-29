import { lazy, Suspense, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './services/authStore';
import AppLayout from './components/Layout/AppLayout';
import ErrorBoundary from './components/Common/ErrorBoundary';
import { Skeleton, SkeletonCard, SkeletonKpiRow } from './components/Common/Skeleton';
import LoginPage from './pages/Login/LoginPage';
import { applyPreferences, fetchUserPreferences, loadLocalPreferences } from './services/preferences';

// Route-based code splitting — each page loads on demand
const DashboardPage = lazy(() => import('./pages/Dashboard/DashboardPage'));
const TurbineDetailPage = lazy(() => import('./pages/TurbineDetail/TurbineDetailPage'));
const DiagnosisPage = lazy(() => import('./pages/Diagnosis/DiagnosisPage'));
const PredictionPage = lazy(() => import('./pages/Prediction/PredictionPage'));
const WorkOrderPage = lazy(() => import('./pages/WorkOrder/WorkOrderPage'));
const SettingsPage = lazy(() => import('./pages/Settings/SettingsPage'));
const KnowledgeBasePage = lazy(() => import('./pages/Knowledge/KnowledgeBasePage'));
const DroneSchedulerPage = lazy(() => import('./pages/DroneScheduler/DroneSchedulerPage'));
const IncidentPage = lazy(() => import('./pages/Incident/IncidentPage'));
const FieldModePage = lazy(() => import('./pages/FieldMode/FieldModePage'));

/** 路由级骨架屏：轮廓贴近页面「页头 + KPI 条 + 主体」的通用结构 */
function PageLoader() {
  return (
    <div className="ops-page h-full overflow-hidden p-5" role="status" aria-label="页面加载中">
      <div className="space-y-2 border-b pb-4" style={{ borderColor: 'var(--border-subtle)' }}>
        <Skeleton className="skeleton-text" width={120} height={9} />
        <Skeleton width={240} height={16} radius={5} />
        <Skeleton className="skeleton-text" width={420} />
      </div>
      <div className="mt-4">
        <SkeletonKpiRow count={4} />
      </div>
      <div className="mt-4 grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
        <SkeletonCard lines={5} />
        <SkeletonCard lines={5} />
      </div>
      <span className="sr-only">页面加载中，请稍候</span>
    </div>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function IndexRedirect() {
  const token = useAuthStore((s) => s.token);
  const [landing, setLanding] = useState(() => loadLocalPreferences().landingPage);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const localPrefs = loadLocalPreferences();
    applyPreferences(localPrefs);
    setLanding(localPrefs.landingPage);
    if (!token) {
      setReady(true);
      return () => { cancelled = true; };
    }
    // Wait for server preferences before navigating; after 500ms fall back
    // to the cached local value so the redirect is never blocked for long.
    const timer = window.setTimeout(() => { if (!cancelled) setReady(true); }, 500);
    fetchUserPreferences()
      .then((prefs) => {
        if (!cancelled) setLanding(prefs.landingPage);
      })
      .catch(() => {
        if (!cancelled) setLanding(localPrefs.landingPage);
      })
      .finally(() => {
        window.clearTimeout(timer);
        if (!cancelled) setReady(true);
      });
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [token]);

  if (!ready) return <PageLoader />;
  return <Navigate to={`/${landing || 'dashboard'}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <ErrorBoundary>
              <AppLayout />
            </ErrorBoundary>
          </ProtectedRoute>
        }
      >
        <Route index element={<IndexRedirect />} />
        <Route path="dashboard" element={<Suspense fallback={<PageLoader />}><DashboardPage /></Suspense>} />
        <Route path="drone-scheduler" element={<Suspense fallback={<PageLoader />}><DroneSchedulerPage /></Suspense>} />
        <Route path="turbine/:id" element={<Suspense fallback={<PageLoader />}><TurbineDetailPage /></Suspense>} />
        <Route path="diagnosis" element={<Suspense fallback={<PageLoader />}><DiagnosisPage /></Suspense>} />
        <Route path="prediction" element={<Suspense fallback={<PageLoader />}><PredictionPage /></Suspense>} />
        <Route path="workorder" element={<Suspense fallback={<PageLoader />}><WorkOrderPage /></Suspense>} />
        <Route path="knowledge" element={<Suspense fallback={<PageLoader />}><KnowledgeBasePage /></Suspense>} />
        <Route path="settings" element={<Suspense fallback={<PageLoader />}><SettingsPage /></Suspense>} />
        <Route path="incident" element={<Suspense fallback={<PageLoader />}><IncidentPage /></Suspense>} />
        <Route path="field-mode" element={<Suspense fallback={<PageLoader />}><FieldModePage /></Suspense>} />
      </Route>
    </Routes>
  );
}
