interface Props {
  filters: Record<string, string>;
  onChange: (f: Record<string, string>) => void;
}

type FilterKey = 'region' | 'model' | 'status' | 'hi_min';

const REGIONS = ['', '榆林靖边风场A区', '榆林定边风场B区', '榆林横山风场C区'];
const MODELS = ['', 'Goldwind GW155-3.3MW', 'Envision EN-156/3.3', 'Mingyang MySE3.2-156'];
const SELECT_CLASS = 'bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 cursor-pointer outline-none focus:border-accent-blue';
const INPUT_CLASS = 'w-16 bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 outline-none focus:border-accent-blue';

export default function FilterPanel({ filters, onChange }: Props) {
  const updateFilter = (key: FilterKey, val: string) => {
    const next = { ...filters, [key]: val };
    if (!val) delete next[key];
    onChange(next);
  };

  return (
    <div className="absolute top-3 left-3 z-[500] flex gap-1.5 glass-panel rounded-lg px-2.5 py-1.5 text-[11px]">
      <select
        value={filters.region || ''}
        onChange={(e) => updateFilter('region', e.target.value)}
        className={SELECT_CLASS}
      >
        {REGIONS.map((r) => (
          <option key={r} value={r} className="bg-bg-card">
            {r || '全部风场'}
          </option>
        ))}
      </select>
      <select
        value={filters.model || ''}
        onChange={(e) => updateFilter('model', e.target.value)}
        className={SELECT_CLASS}
      >
        {MODELS.map((m) => (
          <option key={m} value={m} className="bg-bg-card">
            {m || '全部机型'}
          </option>
        ))}
      </select>
      <select
        value={filters.status || ''}
        onChange={(e) => updateFilter('status', e.target.value)}
        className={SELECT_CLASS}
      >
        <option value="">全部状态</option>
        <option value="normal">正常</option>
        <option value="warning">预警</option>
        <option value="fault">故障</option>
      </select>
      <input
        type="number"
        placeholder="HI >="
        value={filters.hi_min || ''}
        onChange={(e) => updateFilter('hi_min', e.target.value)}
        className={INPUT_CLASS}
      />
      {Object.keys(filters).length > 0 && (
        <button
          onClick={() => onChange({})}
          className="text-text-muted hover:text-accent-red px-1.5 transition-colors"
        >
          清除
        </button>
      )}
    </div>
  );
}
