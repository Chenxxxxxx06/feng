import { lazy, Suspense, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './services/authStore';
import AppLayout from './components/Layout/AppLayout';
import ErrorBoundary from './components/Common/ErrorBoundary';
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

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full text-text-muted text-sm">
      <span className="animate-pulse">加载中...</span>
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

  useEffect(() => {
    let cancelled = false;
    const localPrefs = loadLocalPreferences();
    applyPreferences(localPrefs);
    setLanding(localPrefs.landingPage);
    if (!token) return () => { cancelled = true; };
    fetchUserPreferences()
      .then((prefs) => {
        if (!cancelled) setLanding(prefs.landingPage);
      })
      .catch(() => {
        if (!cancelled) setLanding(localPrefs.landingPage);
      });
    return () => { cancelled = true; };
  }, [token]);

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
      </Route>
    </Routes>
  );
}
