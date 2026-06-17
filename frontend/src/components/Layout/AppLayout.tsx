import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../services/authStore';

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
    path: '/settings',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
      </svg>
    ), label: '系统设置',
  },
];

export default function AppLayout() {
  const location = useLocation();
  const { user, logout } = useAuthStore();

  return (
    <div className="flex h-screen w-screen" style={{ background: '#071A35' }}>
      <aside
        className="w-[200px] flex-shrink-0 flex flex-col border-r"
        style={{ background: 'linear-gradient(180deg, #0A1F3F 0%, #071A35 100%)', borderColor: 'rgba(59,130,246,0.10)' }}
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

        <nav className="flex-1 py-5 px-3 space-y-1">
          <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-widest text-text-muted">导航菜单</p>
          {navItems.map((item) => {
            const active = location.pathname.startsWith(item.path);
            return (
              <NavLink key={item.path} to={item.path}
                className={`sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                  active ? 'text-[#F1F5F9]' : 'text-text-secondary hover:text-[#E2E8F0]'
                }`}
                style={active ? { background: 'rgba(59,130,246,0.14)', boxShadow: '0 0 12px rgba(59,130,246,0.08)' } : {}}
              >
                <span className={`flex-shrink-0 transition-colors duration-200 ${active ? 'text-[#3B82F6]' : ''}`}>{item.icon}</span>
                <span>{item.label}</span>
                {active && <span className="ml-auto w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: '#3B82F6', boxShadow: '0 0 8px rgba(59,130,246,0.6)' }} />}
              </NavLink>
            );
          })}
        </nav>

        <div className="px-4 py-3 mx-3 mb-3 rounded-xl" style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.08)' }}>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: '#10B981' }} />
              <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: '#10B981' }} />
            </span>
            <span className="text-[11px] text-text-muted">系统运行正常</span>
          </div>
        </div>

        <div className="p-4 border-t mx-3" style={{ borderColor: 'rgba(59,130,246,0.08)' }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold text-white flex-shrink-0"
              style={{ background: 'linear-gradient(135deg, #3B82F6, #8B5CF6)', boxShadow: '0 2px 8px rgba(59,130,246,0.25)' }}>
              {user?.username?.[0]?.toUpperCase() || 'A'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold truncate text-text-primary">{user?.username || 'admin'}</p>
              <button onClick={logout} className="text-[10px] text-text-muted hover:text-accent-red transition-colors duration-150">退出登录</button>
            </div>
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-hidden" style={{ background: '#071A35' }}>
        <Outlet />
      </main>
    </div>
  );
}
