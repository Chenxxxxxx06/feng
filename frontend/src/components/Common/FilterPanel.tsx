import { useEffect, useState, useMemo } from 'react';
import { predictionService } from '../../services/predictionService';
import api from '../../services/api';

interface Props {
  filters: Record<string, string>;
  onChange: (f: Record<string, string>) => void;
}

type FilterKey = 'region' | 'model' | 'status' | 'hi_min';

const SELECT_CLASS =
  'bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 cursor-pointer outline-none focus:border-accent-blue';
const INPUT_CLASS =
  'w-16 bg-transparent text-text-primary border border-border-subtle rounded-md px-2 py-1 outline-none focus:border-accent-blue';

export default function FilterPanel({ filters, onChange }: Props) {
  const [regions, setRegions] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);

  // Load turbine metadata once for filter options
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const turbines = await predictionService.getTurbines();
        if (cancelled) return;
        const uniqueRegions = [...new Set(turbines.map((t) => t.region).filter(Boolean))].sort();
        const uniqueModels = [...new Set(turbines.map((t) => t.model).filter(Boolean))].sort();
        setRegions(uniqueRegions as string[]);
        setModels(uniqueModels as string[]);
      } catch {
        // Keep static fallback values
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const updateFilter = (key: FilterKey, val: string) => {
    const next = { ...filters, [key]: val };
    if (!val) delete next[key];
    onChange(next);
  };

  return (
    <div className="absolute top-3 left-3 z-[500] flex gap-1.5 glass-panel rounded-lg px-2.5 py-1.5 text-[11px]">
      {/* Region filter */}
      <select
        value={filters.region || ''}
        onChange={(e) => updateFilter('region', e.target.value)}
        className={SELECT_CLASS}
      >
        <option value="" className="bg-bg-card">全部风场</option>
        {(regions.length > 0 ? regions : ['陕北', '关中', '陕南']).map((r) => (
          <option key={r} value={r} className="bg-bg-card">{r}</option>
        ))}
      </select>

      {/* Model filter */}
      <select
        value={filters.model || ''}
        onChange={(e) => updateFilter('model', e.target.value)}
        className={SELECT_CLASS}
      >
        <option value="" className="bg-bg-card">全部机型</option>
        {(models.length > 0 ? models : ['金风GW150-3MW', '远景EN-156/3.3']).map((m) => (
          <option key={m} value={m} className="bg-bg-card">{m}</option>
        ))}
      </select>

      {/* Status filter */}
      <select
        value={filters.status || ''}
        onChange={(e) => updateFilter('status', e.target.value)}
        className={SELECT_CLASS}
      >
        <option value="" className="bg-bg-card">全部状态</option>
        <option value="normal" className="bg-bg-card">正常</option>
        <option value="warning" className="bg-bg-card">预警</option>
        <option value="fault" className="bg-bg-card">故障</option>
      </select>

      {/* HI threshold */}
      <input
        type="number"
        placeholder="HI >="
        value={filters.hi_min || ''}
        onChange={(e) => updateFilter('hi_min', e.target.value)}
        className={INPUT_CLASS}
      />

      {/* Clear */}
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
