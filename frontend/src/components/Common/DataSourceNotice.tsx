import type { DataProvenance } from '../../services/dataProvenance';

interface DataSourceNoticeProps {
  provenance: DataProvenance;
  className?: string;
}

const SOURCE_COLORS: Record<DataProvenance['source_type'], string> = {
  historical: '#22D3EE',
  simulated: '#F59E0B',
  demo: '#A78BFA',
};

function formatDateTime(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export default function DataSourceNotice({ provenance, className = '' }: DataSourceNoticeProps) {
  const start = formatDateTime(provenance.data_time_range?.start);
  const end = formatDateTime(provenance.data_time_range?.end);
  const range = start && end ? `${start} 至 ${end}` : end || start;

  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-y px-3 py-2 text-xs text-text-secondary ${className}`}
      style={{ borderColor: 'rgba(148, 163, 184, 0.16)', background: 'rgba(15, 23, 42, 0.32)' }}
      role="note"
      aria-label="数据来源说明"
    >
      <span className="inline-flex items-center gap-2 font-semibold" style={{ color: SOURCE_COLORS[provenance.source_type] }}>
        <span className="h-2 w-2 rounded-full" style={{ background: SOURCE_COLORS[provenance.source_type] }} aria-hidden="true" />
        {provenance.source_label}
      </span>
      {range && <span>数据范围：{range}</span>}
      <span className="text-text-muted">{provenance.source_description}</span>
    </div>
  );
}
