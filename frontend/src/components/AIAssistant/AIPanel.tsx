import { useCallback, useState } from 'react';
import api from '../../services/api';
import type { AISummary } from '../../types';

interface Props {
  pageType: string;
  pageData?: Record<string, unknown>;
}

export default function AIPanel({ pageType, pageData }: Props) {
  const [summary, setSummary] = useState<AISummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [triggered, setTriggered] = useState(false);

  const fetchSummary = useCallback(() => {
    setTriggered(true);
    setLoading(true);
    api.post('/ai/summary', { page_type: pageType, page_data: pageData || {} })
      .then(({ data }) => setSummary(data))
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [pageType, pageData]);

  return (
    <div className="p-3 max-h-64 overflow-auto">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="text-accent-cyan text-xs">⚡</span>
        <h4 className="text-xs font-medium text-text-secondary">AI 智能总结</h4>
      </div>

      {!triggered ? (
        <button
          onClick={fetchSummary}
          className="w-full rounded border border-accent-cyan/40 bg-accent-cyan/10 px-3 py-2 text-xs text-accent-cyan hover:bg-accent-cyan/20 transition-colors"
        >
          🤖 生成AI总结
        </button>
      ) : loading ? (
        <p className="text-xs text-text-muted animate-pulse">分析中...</p>
      ) : summary ? (
        <div className="space-y-2">
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">关键结论</p>
            <ul className="space-y-1">
              {summary.conclusions.map((c, i) => (
                <li key={i} className="text-xs text-text-primary flex gap-1.5">
                  <span className="text-accent-blue flex-shrink-0">{i + 1}.</span>
                  {c}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">可执行建议</p>
            <ul className="space-y-1">
              {summary.suggestions.map((s, i) => (
                <li key={i} className="text-xs text-accent-yellow flex gap-1.5">
                  <span>▸</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="text-xs text-text-muted">AI服务暂不可用</p>
      )}
    </div>
  );
}
