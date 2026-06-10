import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../services/authStore';

const navItems = [
  { path: '/dashboard', icon: '◉', label: '风场监控' },
  { path: '/diagnosis', icon: '◇', label: '故障诊断' },
  { path: '/prediction', icon: '◎', label: '预测决策' },
  { path: '/workorder', icon: '▣', label: '维修工单' },
  { path: '/settings', icon: '⚙', label: '系统设置' },
];

export default function AppLayout() {
  const location = useLocation();
  const { user, logout } = useAuthStore();

  return (
    <div className="flex h-screen w-screen bg-bg-deep">
      {/* Sidebar */}
      <aside className="w-[220px] flex-shrink-0 flex flex-col border-r border-border-subtle" style={{ background: 'linear-gradient(180deg, #0d1525 0%, #0a101d 100%)' }}>
        {/* Logo */}
        <div className="h-14 flex items-center gap-2.5 px-5 border-b border-border-subtle">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg, rgba(56,139,253,0.3), rgba(57,210,192,0.2))' }}>
            <span className="text-accent-cyan text-base">⟳</span>
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-wide gradient-text">风调预顺</h1>
            <p className="text-[9px] text-text-muted leading-none">PHM 运维系统 v1.0</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-3 space-y-0.5">
          {navItems.map((item) => {
            const active = location.pathname.startsWith(item.path);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={`sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 ${
                  active
                    ? 'text-accent-blue font-medium'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/50'
                }`}
                style={active ? { background: 'rgba(56,139,253,0.08)' } : {}}
              >
                <span className={`text-base ${active ? 'text-accent-blue' : ''}`}>{item.icon}</span>
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        {/* User footer */}
        <div className="p-4 border-t border-border-subtle">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium" style={{ background: 'linear-gradient(135deg, #388bfd, #a371f7)' }}>
              {user?.username?.[0]?.toUpperCase() || 'A'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate">{user?.username || 'admin'}</p>
              <button onClick={logout} className="text-[10px] text-text-muted hover:text-accent-red transition-colors">退出登录</button>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden bg-bg-deep">
        <Outlet />
      </main>
    </div>
  );
}
