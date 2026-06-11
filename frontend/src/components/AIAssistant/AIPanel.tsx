import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { AISummary } from '../../types';

interface Props { pageType: string }

export default function AIPanel({ pageType }: Props) {
  const [summary, setSummary] = useState<AISummary | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.post('/ai/summary', { page_type: pageType, page_data: {} })
      .then(({ data }) => setSummary(data))
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [pageType]);

  return (
    <div className="p-3 max-h-64 overflow-auto">
      <div className="flex items-center gap-2 mb-2.5">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#00E5FF" strokeWidth="2">
          <polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>
        </svg>
        <p className="font-mono text-[9px] uppercase tracking-widest" style={{ color: '#445566' }}>
          // AI_SUMMARY
        </p>
      </div>

      {loading ? (
        <p className="font-mono text-[10px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>
          ANALYZING...
        </p>
      ) : summary ? (
        <div className="space-y-3">
          <div>
            <p className="font-mono text-[9px] uppercase tracking-wider mb-1.5" style={{ color: '#445566' }}>
              {'>'} CONCLUSIONS
            </p>
            <ul className="space-y-1">
              {summary.conclusions.map((c: string, i: number) => (
                <li key={i} className="text-[11px] flex gap-1.5" style={{ color: '#E8ECF1' }}>
                  <span style={{ color: '#00E5FF', fontFamily: '"JetBrains Mono",monospace', flexShrink: 0 }}>
                    [{String(i + 1).padStart(2, '0')}]
                  </span>
                  {c}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-mono text-[9px] uppercase tracking-wider mb-1.5" style={{ color: '#445566' }}>
              {'>'} ACTIONS
            </p>
            <ul className="space-y-1">
              {summary.suggestions.map((s: string, i: number) => (
                <li key={i} className="text-[11px] flex gap-1.5" style={{ color: '#FF9100' }}>
                  <span style={{ color: '#FF9100', flexShrink: 0 }}>&gt;</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
          AI_SERVICE_OFFLINE
        </p>
      )}
    </div>
  );
}
