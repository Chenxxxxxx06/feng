import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useAuthStore } from '../../services/authStore';
import api from '../../services/api';
import ToastHost from '../Common/Toast';
import OnboardingTour, { replayTour } from '../Common/OnboardingTour';
import CopilotFAB from '../AIAssistant/CopilotFAB';
import {
  applyPreferences,
  canShowDesktopDigest,
  fetchUserPreferences,
  loadLocalPreferences,
  markDesktopDigestShown,
  PREFERENCES_UPDATED_EVENT,
  type UserPreferences,
} from '../../services/preferences';

const navItems = [
  {
    path: '/dashboard',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" />
      </svg>
    ), label: '风场监控',
  },
  {
    path: '/drone-scheduler',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L2 19h20L12 2z" />
        <circle cx="12" cy="13" r="3" />
        <line x1="12" y1="16" x2="12" y2="22" />
      </svg>
    ), label: '数据获取',
  },
  {
    path: '/diagnosis',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="9" /><path d="M12 8v5l3 3" />
      </svg>
    ), label: '故障诊断',
  },
  {
    path: '/prediction',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ), label: '预测决策',
  },
  {
    path: '/workorder',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ), label: '维修工单',
  },
  {
    path: '/knowledge',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5Z" />
      </svg>
    ), label: '故障百科',
  },
  {
    path: '/incident',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z" />
        <polyline points="12 6 12 12 16 14" />
        <line x1="8" y1="18" x2="16" y2="18" />
        <line x1="8" y1="21" x2="12" y2="21" />
      </svg>
    ), label: '事件指挥',
  },
  {
    path: '/settings',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
      </svg>
    ), label: '系统设置',
  },
];

// These pages provide live, domain-specific context to their own assistant
// instance. Every other authenticated route receives the layout-level fallback.
const PAGE_MANAGED_COPILOT_ROUTES = [
  '/diagnosis',
  '/drone-scheduler',
  '/incident',
  '/knowledge',
  '/prediction',
  '/settings',
  '/turbine/',
];

function pageManagesCopilot(pathname: string): boolean {
  return PAGE_MANAGED_COPILOT_ROUTES.some((route) => pathname.startsWith(route));
}

const SIDEBAR_MIN = 180;
const SIDEBAR_MAX = 340;
const SIDEBAR_DEFAULT = 200;
const SIDEBAR_WIDTH_KEY = 'app.sidebar.width';

const clampSidebarWidth = (value: number) => Math.max(SIDEBAR_MIN, Math.min(value, SIDEBAR_MAX));

interface DesktopDigestSummary {
  lowHiCount: number;
  todoCount: number;
  threshold: number;
}

export default function AppLayout() {
  const location = useLocation();
  const { user, logout } = useAuthStore();
  const [desktopDigest, setDesktopDigest] = useState<DesktopDigestSummary | null>(null);
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'down'>('checking');
  const [backendCheckedAt, setBackendCheckedAt] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY));
    return Number.isFinite(saved) && saved > 0 ? clampSidebarWidth(saved) : SIDEBAR_DEFAULT;
  });
  const resizing = useRef(false);

  useEffect(() => {
    applyPreferences(loadLocalPreferences());
    const handlePreferences = (event: Event) => {
      const prefs = (event as CustomEvent<UserPreferences>).detail || loadLocalPreferences();
      document.body.classList.toggle('compact-workspace', prefs.compactWorkspace);
    };
    window.addEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
    return () => window.removeEventListener(PREFERENCES_UPDATED_EVENT, handlePreferences);
  }, []);

  // 后端连通性探测：每 60 秒一次。指示灯必须反映真实探测结果，
  // 演示途中后端挂掉时能立刻从侧边栏看出来，而不是永远显示绿灯。
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      try {
        const { data } = await api.get('/health', { timeout: 8000 });
        if (cancelled) return;
        setBackendStatus(data?.status === 'ok' ? 'ok' : 'down');
      } catch {
        if (!cancelled) setBackendStatus('down');
      } finally {
        if (!cancelled) {
          setBackendCheckedAt(
            new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          );
        }
      }
    };
    void probe();
    const timer = window.setInterval(probe, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const loadDigest = async () => {
      const prefs = await fetchUserPreferences().catch(() => loadLocalPreferences());
      if (!canShowDesktopDigest(prefs)) return;
      const [alertsResult, ordersResult] = await Promise.allSettled([
        api.get('/settings/threshold-alerts'),
        api.get('/workorders/'),
      ]);
      if (cancelled) return;

      const alerts = alertsResult.status === 'fulfilled' ? alertsResult.value.data : null;
      const rawOrders = ordersResult.status === 'fulfilled' ? ordersResult.value.data : [];
      const orders = Array.isArray(rawOrders) ? rawOrders : rawOrders.workorders || [];
      const todoCount = orders.filter((order: { status?: string }) => (
        ['pending', 'assigned', 'in_progress', 'review'].includes(order.status || '')
      )).length;
      setDesktopDigest({
        lowHiCount: alerts?.low_count || 0,
        threshold: alerts?.threshold ?? 70,
        todoCount,
      });
      markDesktopDigestShown();
    };
    loadDigest();
    return () => { cancelled = true; };
  }, [user]);

  useEffect(() => {
    const handleMove = (event: MouseEvent) => {
      if (!resizing.current) return;
      const next = clampSidebarWidth(event.clientX);
      setSidebarWidth(next);
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(next));
    };
    const handleUp = () => {
      resizing.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    return () => {
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
    };
  }, []);

  const startResize = (event: ReactMouseEvent) => {
    resizing.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    event.preventDefault();
  };

  return (
    <div className="flex h-screen w-screen" style={{ background: '#071A35' }}>
      <aside
        className="relative flex flex-shrink-0 flex-col border-r"
        style={{ width: sidebarWidth, background: 'linear-gradient(180deg, #0A1F3F 0%, #071A35 100%)', borderColor: 'rgba(59,130,246,0.10)' }}
      >
        <div className="h-16 flex items-center gap-3 px-5 border-b" style={{ borderColor: 'rgba(59,130,246,0.08)' }}>
          <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'linear-gradient(135deg, #3B82F6 0%, #2563EB 100%)', boxShadow: '0 4px 12px rgba(59,130,246,0.3)' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
              <circle cx="12" cy="12" r="3" fill="white" />
            </svg>
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-bold tracking-wide gradient-text">风调预顺</h1>
            <p className="text-[10px] text-text-muted leading-none mt-0.5">PHM 预测性运维系统</p>
          </div>
        </div>

        <nav className="flex-1 min-h-0 overflow-y-auto py-4 px-3 space-y-0.5" data-tour="nav" aria-label="主导航">
          <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-widest text-text-muted">导航菜单</p>
          {navItems.map((item) => {
            const active = location.pathname.startsWith(item.path);
            return (
              <NavLink key={item.path} to={item.path}
                aria-current={active ? 'page' : undefined}
                title={item.label}
                className={`sidebar-link flex items-center gap-3 px-3 py-2 rounded-xl text-[13px] font-medium transition-all duration-200 ${
                  active ? 'text-[#F1F5F9]' : 'text-text-secondary hover:text-[#E2E8F0] hover:bg-bg-hover'
                }`}
                style={active ? { background: 'rgba(59,130,246,0.14)', boxShadow: '0 0 12px rgba(59,130,246,0.08)' } : {}}
              >
                <span className={`flex-shrink-0 transition-colors duration-200 ${active ? 'text-[#3B82F6]' : ''}`} aria-hidden="true">{item.icon}</span>
                <span className="truncate">{item.label}</span>
                {active && <span className="ml-auto w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: '#3B82F6', boxShadow: '0 0 8px rgba(59,130,246,0.6)' }} />}
              </NavLink>
            );
          })}
        </nav>

        {/* 后端连通性指示：反映真实探测结果，不写死绿灯。
            语义限定为"后端连接"，避免与顶栏的机组健康状态混淆。 */}
        <div
          className="px-4 py-3 mx-3 mb-3 rounded-xl"
          style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.08)' }}
          title={
            backendStatus === 'ok'
              ? `后端服务连通（最近探测 ${backendCheckedAt ?? '—'}）`
              : backendStatus === 'down'
                ? '后端服务无响应，页面数据可能为陈旧缓存'
                : '正在探测后端服务'
          }
        >
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {backendStatus === 'ok' && (
                <span
                  className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
                  style={{ background: 'var(--accent-green)' }}
                />
              )}
              <span
                className="relative inline-flex rounded-full h-2 w-2"
                style={{
                  background:
                    backendStatus === 'ok'
                      ? 'var(--accent-green)'
                      : backendStatus === 'down'
                        ? 'var(--accent-red)'
                        : 'var(--text-muted)',
                }}
              />
            </span>
            <span className="text-[11px] text-text-muted">
              {backendStatus === 'ok' ? '后端服务连通' : backendStatus === 'down' ? '后端服务无响应' : '正在探测后端…'}
            </span>
          </div>
        </div>

        <div className="p-4 border-t mx-3" style={{ borderColor: 'rgba(59,130,246,0.08)' }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
              style={{ background: 'linear-gradient(135deg, #3B82F6, #8B5CF6)', boxShadow: '0 2px 8px rgba(59,130,246,0.25)' }}>
              {user?.username?.[0]?.toUpperCase() || 'A'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold truncate text-text-primary" title={user?.username || 'admin'}>{user?.username || 'admin'}</p>
              <div className="flex items-center gap-2">
                <button onClick={logout} className="text-[10px] text-text-muted hover:text-accent-red transition-colors duration-150">退出登录</button>
                <span className="text-[10px] text-text-muted/40">·</span>
                <button
                  onClick={replayTour}
                  className="text-[10px] text-text-muted hover:text-accent-blue transition-colors duration-150"
                  title="重新播放新手引导"
                >
                  新手引导
                </button>
              </div>
            </div>
          </div>
        </div>
        <button
          type="button"
          aria-label="调整侧边栏宽度"
          title="拖动调整侧边栏宽度"
          onMouseDown={startResize}
          className="absolute right-[-4px] top-0 z-20 h-full w-2 cursor-col-resize bg-transparent transition-colors hover:bg-accent-blue/30"
        >
          <span className="absolute right-[3px] top-1/2 h-10 w-px -translate-y-1/2 rounded bg-border-active opacity-60" />
        </button>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden" style={{ background: '#071A35' }}>
        {desktopDigest && (
          <DesktopDigestToast summary={desktopDigest} onClose={() => setDesktopDigest(null)} />
        )}
        <Outlet />
      </main>

      <ToastHost />
      {!pageManagesCopilot(location.pathname) && <CopilotFAB />}
      <OnboardingTour enabled={Boolean(user) && location.pathname.startsWith('/dashboard')} />
    </div>
  );
}

function DesktopDigestToast({ summary, onClose }: { summary: DesktopDigestSummary; onClose: () => void }) {
  const [position, setPosition] = useState({ x: window.innerWidth - 332, y: 20 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const hasRisk = summary.lowHiCount > 0 || summary.todoCount > 0;

  const onMouseDown = (e: React.MouseEvent) => {
    setDragging(true);
    setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
    e.preventDefault();
  };

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      const newX = Math.max(0, Math.min(e.clientX - dragStart.x, window.innerWidth - 300));
      const newY = Math.max(0, Math.min(e.clientY - dragStart.y, window.innerHeight - 160));
      setPosition({ x: newX, y: newY });
    };
    const onUp = () => setDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragging, dragStart]);

  return (
    <div
      className={`pointer-events-none fixed z-[900] w-[300px] rounded-lg border border-border-card bg-bg-panel/95 p-4 shadow-2xl backdrop-blur transition-shadow ${
        dragging ? 'shadow-[0_0_30px_rgba(59,130,246,0.3)] cursor-grabbing select-none' : 'cursor-auto'
      }`}
      style={{ left: position.x, top: position.y }}
    >
      <div
        className="pointer-events-auto flex items-start justify-between gap-3 cursor-grab active:cursor-grabbing"
        onMouseDown={onMouseDown}
      >
        <div>
          <p className="text-xs font-semibold text-text-primary">桌面摘要</p>
          <p className={`mt-1 text-[11px] ${hasRisk ? 'text-accent-yellow' : 'text-accent-green'}`}>
            {hasRisk ? '存在待关注事项' : '当前暂无重点待办'}
          </p>
          <p className="text-[9px] text-text-muted/50 mt-0.5">拖拽标题栏可移动</p>
        </div>
        <button onClick={onClose} className="text-sm text-text-muted hover:text-text-primary cursor-pointer" aria-label="关闭桌面摘要">
          ×
        </button>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-md border border-border-default bg-bg-card px-3 py-2">
          <p className="text-[10px] text-text-muted">低 HI 告警</p>
          <p className="mt-1 font-mono text-lg font-bold text-accent-yellow">{summary.lowHiCount}</p>
          <p className="text-[10px] text-text-muted">阈值 {summary.threshold}</p>
        </div>
        <div className="rounded-md border border-border-default bg-bg-card px-3 py-2">
          <p className="text-[10px] text-text-muted">待办工单</p>
          <p className="mt-1 font-mono text-lg font-bold text-accent-blue">{summary.todoCount}</p>
          <p className="text-[10px] text-text-muted">待处理</p>
        </div>
      </div>
    </div>
  );
}
