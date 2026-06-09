interface Props {
  filters: Record<string, string>;
  onChange: (f: Record<string, string>) => void;
}

const REGIONS = ['', '陕北', '关中', '陕南'];
const MODELS = ['', '1.5MW', '2MW', '3MW', '5MW+'];

export default function FilterPanel({ filters, onChange }: Props) {
  const on = (key: string, val: string) => {
    const next = { ...filters, [key]: val };
    if (!val) delete next[key];
    onChange(next);
  };

  return (
    <div className="absolute top-3 left-3 z-[500] flex gap-1.5 glass-panel rounded-lg px-2.5 py-1.5 text-[11px]">
      <select value={filters.region || ''} onChange={(e) => on('region', e.target.value)}
        className="bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 cursor-pointer outline-none focus:border-accent-blue">
        {REGIONS.map((r) => <option key={r} value={r} className="bg-bg-card">{r || '全部区域'}</option>)}
      </select>
      <select value={filters.model || ''} onChange={(e) => on('model', e.target.value)}
        className="bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 cursor-pointer outline-none focus:border-accent-blue">
        {MODELS.map((m) => <option key={m} value={m} className="bg-bg-card">{m || '全部机型'}</option>)}
      </select>
      <select value={filters.status || ''} onChange={(e) => on('status', e.target.value)}
        className="bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 cursor-pointer outline-none focus:border-accent-blue">
        <option value="">全部状态</option>
        <option value="normal">正常</option>
        <option value="warning">预警</option>
        <option value="fault">故障</option>
      </select>
      <input type="number" placeholder="HI ≥" value={filters.hi_min || ''}
        onChange={(e) => on('hi_min', e.target.value)}
        className="w-16 bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 outline-none focus:border-accent-blue" />
      {Object.keys(filters).length > 0 && (
        <button onClick={() => onChange({})}
          className="text-text-muted hover:text-accent-red px-1.5 transition-colors">✕</button>
      )}
    </div>
  );
}
