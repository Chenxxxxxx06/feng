import { CHAIN_STATUS_META, SEGMENT_META } from '../../services/agentTraceService';
import type { ExecutionChainStep } from '../../services/agentTraceService';

interface Props {
  step: ExecutionChainStep;
  /** 最后一张卡不画连接线 */
  isLast?: boolean;
}

/**
 * 执行链单步状态卡：
 * [✓]理解 意图=xxx 槽位=xxx(置信0.94)
 * [▶]工具 query_xxx→结果摘要(127ms)
 * [⛔]守护 require_confirmation—L2写操作
 */
export default function StepCard({ step, isLast }: Props) {
  const statusMeta = CHAIN_STATUS_META[step.status];
  const segmentMeta = SEGMENT_META[step.segment];

  return (
    <div className="relative pl-5">
      {/* 时间轴 */}
      <span
        className="absolute left-[5px] top-3 h-2 w-2 rounded-full"
        style={{ background: segmentMeta.color, boxShadow: `0 0 8px ${segmentMeta.color}` }}
      />
      {!isLast && (
        <span className="absolute left-[9px] top-6 bottom-[-6px] w-px bg-border-default" />
      )}

      <div className={`rounded-lg border px-2.5 py-2 transition-colors ${statusMeta.border} ${statusMeta.bg} ${
        step.status === 'running' ? 'animate-pulse' : ''
      }`}>
        <div className="flex items-start gap-1.5">
          <span className={`mt-[1px] font-mono text-[11px] leading-4 ${statusMeta.text}`}>
            [{statusMeta.icon}]
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className={`text-[11px] font-semibold ${segmentMeta.text}`}>
                {segmentMeta.icon} {step.title}
              </span>
              {step.meta && (
                <span className="truncate rounded bg-bg-secondary/70 px-1 font-mono text-[9px] text-text-muted">
                  {step.meta}
                </span>
              )}
              <span className={`ml-auto shrink-0 text-[9px] ${statusMeta.text}`}>{statusMeta.label}</span>
            </div>
            <p className="mt-0.5 break-words text-[10px] leading-4 text-text-secondary">
              {step.detail}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
