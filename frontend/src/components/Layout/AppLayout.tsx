import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../services/authStore';

const navItems = [
  { id: '01', path: '/dashboard', label: '风场监控', icon: GridIcon },
  { id: '02', path: '/diagnosis', label: '故障诊断', icon: ScanIcon },
  { id: '03', path: '/prediction', label: '预测决策', icon: GraphIcon },
  { id: '04', path: '/workorder', label: '维修工单', icon: WrenchIcon },
  { id: '05', path: '/settings', label: '系统设置', icon: CogIcon },
];

export default function AppLayout() {
  const location = useLocation();
  const { user, logout } = useAuthStore();

  return (
    <div className="flex h-screen w-screen" style={{ background: '#020204' }}>
      {/* ── Terminal Command Panel Sidebar ── */}
      <aside
        className="w-[200px] flex-shrink-0 flex flex-col"
        style={{
          background: '#0A0C10',
          borderRight: '1px solid rgba(0,229,255,0.12)',
        }}
      >
        {/* Logo block */}
        <div
          className="h-14 flex items-center gap-2.5 px-4"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div
            className="w-8 h-8 flex items-center justify-center flex-shrink-0"
            style={{
              border: '1px solid rgba(0,229,255,0.2)',
              borderRadius: '2px',
              background: 'rgba(0,229,255,0.04)',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#00E5FF" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
            </svg>
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold tracking-wider font-display" style={{ color: '#E8ECF1' }}>
              风调预顺
            </h1>
            <p className="text-[9px] font-mono uppercase tracking-widest" style={{ color: '#445566' }}>
              SYS::PHM v2.0
            </p>
          </div>
        </div>

        {/* Nav — terminal style */}
        <nav className="flex-1 py-4 px-3 space-y-px">
          <p
            className="px-3 pb-2 font-mono text-[9px] uppercase tracking-widest"
            style={{ color: '#445566' }}
          >
            // Navigation
          </p>
          {navItems.map((item) => {
            const active = location.pathname.startsWith(item.path);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={`side-link flex items-center gap-2.5 px-3 py-2.5 text-[12px] font-medium transition-all ${
                  active ? 'active' : ''
                }`}
                style={{
                  color: active ? '#E8ECF1' : '#8899AA',
                  background: active ? 'rgba(0,229,255,0.04)' : 'transparent',
                  borderLeft: active ? '2px solid #00E5FF' : '2px solid transparent',
                }}
              >
                <span className="font-mono text-[9px] w-5" style={{ color: active ? '#00E5FF' : '#445566' }}>
                  {item.id}
                </span>
                <item.icon active={active} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* User footer */}
        <div
          className="p-4"
          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div className="flex items-center gap-2.5">
            <div
              className="w-8 h-8 flex items-center justify-center text-xs font-bold flex-shrink-0"
              style={{
                background: 'rgba(0,229,255,0.06)',
                border: '1px solid rgba(0,229,255,0.15)',
                borderRadius: '2px',
                color: '#00E5FF',
                fontFamily: '"Rajdhani",sans-serif',
                fontSize: '14px',
              }}
            >
              {(user?.username || 'A')[0].toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium truncate" style={{ color: '#E8ECF1' }}>
                {user?.username || 'admin'}
              </p>
              <button
                onClick={logout}
                className="text-[10px] font-mono uppercase tracking-wider transition-colors"
                style={{ color: '#445566' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = '#FF1744')}
                onMouseLeave={(e) => (e.currentTarget.style.color = '#445566')}
              >
                [LOGOUT]
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* ── Main — control center viewport ── */}
      <main className="flex-1 overflow-hidden hex-bg scan-line" style={{ background: '#020204' }}>
        <Outlet />
      </main>
    </div>
  );
}

/* ── SVG Icons ── */
const icn = (active: boolean) => active ? '#00E5FF' : '#445566';

function GridIcon({ active }: { active: boolean }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={icn(active)} strokeWidth="1.5"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>;
}
function ScanIcon({ active }: { active: boolean }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={icn(active)} strokeWidth="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>;
}
function GraphIcon({ active }: { active: boolean }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={icn(active)} strokeWidth="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>;
}
function WrenchIcon({ active }: { active: boolean }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={icn(active)} strokeWidth="1.5"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>;
}
function CogIcon({ active }: { active: boolean }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={icn(active)} strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>;
}
