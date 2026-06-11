interface Props { filters: Record<string, string>; onChange: (f: Record<string, string>) => void }

const REGIONS = ['', '陕北', '关中', '陕南'];
const MODELS = ['', '1.5MW', '2MW', '3MW', '5MW+'];

export default function FilterPanel({ filters, onChange }: Props) {
  const on = (key: string, val: string) => {
    const next = { ...filters, [key]: val };
    if (!val) delete next[key];
    onChange(next);
  };

  const hasFilters = Object.keys(filters).length > 0;

  return (
    <div
      className="absolute top-3 left-3 z-[500] flex items-center gap-1.5 px-3 py-2"
      style={{
        background: 'rgba(17,20,28,0.92)',
        border: '1px solid rgba(0,229,255,0.15)',
        borderRadius: '2px',
        backdropFilter: 'blur(8px)',
        boxShadow: '0 0 20px rgba(0,0,0,0.6)',
      }}
    >
      <select value={filters.region || ''} onChange={(e) => on('region', e.target.value)}
        className="select-hud text-[11px]" style={{ minWidth: 80 }}>
        {REGIONS.map(r => <option key={r} value={r}>{r || 'ALL_REGIONS'}</option>)}
      </select>
      <select value={filters.model || ''} onChange={(e) => on('model', e.target.value)}
        className="select-hud text-[11px]" style={{ minWidth: 80 }}>
        {MODELS.map(m => <option key={m} value={m}>{m || 'ALL_MODELS'}</option>)}
      </select>
      <select value={filters.status || ''} onChange={(e) => on('status', e.target.value)}
        className="select-hud text-[11px]" style={{ minWidth: 80 }}>
        <option value="">ALL_STATUS</option>
        <option value="normal">NORMAL</option>
        <option value="warning">WARNING</option>
        <option value="fault">FAULT</option>
      </select>
      <input type="number" placeholder="HI_MIN" value={filters.hi_min || ''}
        onChange={(e) => on('hi_min', e.target.value)}
        className="input-hud text-[11px] w-20" style={{ padding: '7px 10px' }} />
      {hasFilters && (
        <button onClick={() => onChange({})}
          className="w-5 h-5 flex items-center justify-center transition-colors"
          style={{ color: '#445566' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = '#FF1744')}
          onMouseLeave={(e) => (e.currentTarget.style.color = '#445566')}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      )}
    </div>
  );
}
