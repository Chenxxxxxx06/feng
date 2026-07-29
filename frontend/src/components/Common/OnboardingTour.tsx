import { useCallback, useEffect, useLayoutEffect, useState } from 'react';

/**
 * 首次访问引导 —— 零第三方依赖的遮罩 + 气泡指引。
 *
 * 目标元素通过 data-tour="<key>" 标记；找不到目标时气泡自动居中展示，
 * 因此即使某个功能被隐藏，引导流程也不会中断。
 * 完成或跳过后写入 localStorage，之后不再自动弹出（可在系统设置里重看）。
 */

export const TOUR_STORAGE_KEY = 'app.onboarding.v1.done';
export const TOUR_REPLAY_EVENT = 'app-onboarding-replay';

interface TourStep {
  target?: string;
  title: string;
  body: string;
  /** 气泡相对目标的位置 */
  placement?: 'right' | 'left' | 'top' | 'bottom' | 'center';
}

const STEPS: TourStep[] = [
  {
    title: '欢迎使用「风调预顺」风电 PHM 平台',
    body: '本平台面向风电场的预测性运维：从数据采集、故障诊断、寿命预测，一直到工单审核、维护窗口、执行与复盘，形成一条可审计的闭环。以下用 2 步说明从哪里开始。',
    placement: 'center',
  },
  {
    target: 'nav',
    title: '第一步 · 左侧导航按业务闭环排列',
    body: '导航自上而下即为业务流：风场监控 → 数据获取 → 故障诊断 → 预测决策 → 维修工单。维护窗口与方案审核已整合到维修工单。日常巡检从「风场监控」进入即可。',
    placement: 'right',
  },
  {
    target: 'copilot',
    title: '第二步 · AI 助手随时可唤起',
    body: '右下角的 Copilot 能读取当前页面的真实数据并给出解释与建议，也可执行受审批约束的操作。所有 AI 结论均标注数据来源，可追溯。',
    placement: 'left',
  },
];

interface Rect { top: number; left: number; width: number; height: number }

const PAD = 8;

function readRect(target?: string): Rect | null {
  if (!target) return null;
  const el = document.querySelector<HTMLElement>(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) return null;
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 };
}

function bubblePosition(rect: Rect | null, placement: TourStep['placement']): React.CSSProperties {
  const W = 340;
  const H = 210;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!rect || placement === 'center') {
    return { left: Math.max(16, (vw - W) / 2), top: Math.max(16, (vh - H) / 2) };
  }
  let left: number;
  let top: number;
  switch (placement) {
    case 'left':
      left = rect.left - W - 12;
      top = rect.top + rect.height / 2 - H / 2;
      break;
    case 'top':
      left = rect.left + rect.width / 2 - W / 2;
      top = rect.top - H - 12;
      break;
    case 'bottom':
      left = rect.left + rect.width / 2 - W / 2;
      top = rect.top + rect.height + 12;
      break;
    case 'right':
    default:
      left = rect.left + rect.width + 12;
      top = rect.top + rect.height / 2 - H / 2;
      break;
  }
  // 兜底：任何方向都不能越出视口
  left = Math.min(Math.max(12, left), vw - W - 12);
  top = Math.min(Math.max(12, top), vh - H - 12);
  return { left, top };
}

export function hasSeenTour(): boolean {
  try { return localStorage.getItem(TOUR_STORAGE_KEY) === '1'; } catch { return true; }
}

/**
 * 供「系统设置」「侧边栏」等入口手动重放引导。
 * 引导的关键锚点在风场监控页，因此不在该页时先跳转再开始。
 */
export function replayTour() {
  try { localStorage.removeItem(TOUR_STORAGE_KEY); } catch { /* ignore */ }
  if (!window.location.pathname.startsWith('/dashboard')) {
    window.location.assign('/dashboard?tour=1');
    return;
  }
  window.dispatchEvent(new Event(TOUR_REPLAY_EVENT));
}

export default function OnboardingTour({ enabled }: { enabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    const forced = new URLSearchParams(window.location.search).get('tour') === '1';
    if (!forced && hasSeenTour()) return;
    // 等页面首屏内容挂载完再开始，保证能测到目标元素
    const timer = window.setTimeout(() => setOpen(true), forced ? 400 : 900);
    return () => window.clearTimeout(timer);
  }, [enabled]);

  useEffect(() => {
    const replay = () => { setIndex(0); setOpen(true); };
    window.addEventListener(TOUR_REPLAY_EVENT, replay);
    return () => window.removeEventListener(TOUR_REPLAY_EVENT, replay);
  }, []);

  const finish = useCallback(() => {
    try { localStorage.setItem(TOUR_STORAGE_KEY, '1'); } catch { /* ignore */ }
    setOpen(false);
    setIndex(0);
    // 清掉 ?tour=1，避免刷新时再次自动播放
    if (window.location.search.includes('tour=1')) {
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    setRect(readRect(STEPS[index]?.target));
  }, [open, index, tick]);

  useEffect(() => {
    if (!open) return;
    const onResize = () => setTick((t) => t + 1);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') setIndex((i) => (i >= STEPS.length - 1 ? (finish(), i) : i + 1));
      else if (e.key === 'ArrowLeft') setIndex((i) => Math.max(0, i - 1));
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, finish]);

  if (!open) return null;

  const step = STEPS[index];
  const isLast = index === STEPS.length - 1;

  return (
    <div role="dialog" aria-modal="true" aria-label="新手引导">
      {/* 拦截层：引导期间避免误触发页面跳转；点击空白处结束引导 */}
      <div
        className="fixed inset-0 z-[2999]"
        onClick={finish}
        aria-hidden="true"
        style={rect ? { background: 'transparent' } : undefined}
      />
      {rect ? (
        <div className="tour-spotlight" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
      ) : (
        <div className="tour-mask" onClick={finish} />
      )}

      <div className="tour-bubble" style={bubblePosition(rect, step.placement)}>
        <div className="flex items-center justify-between gap-3">
          <span className="badge badge-info">引导 {index + 1} / {STEPS.length}</span>
          <button type="button" onClick={finish} className="btn btn-ghost btn-xs" aria-label="跳过新手引导">跳过</button>
        </div>

        <h3 className="mt-3 text-[13px] font-bold leading-snug text-text-primary">{step.title}</h3>
        <p className="mt-2 text-[11px] leading-[1.7] text-text-secondary">{step.body}</p>

        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="tour-step-dots" aria-hidden="true">
            {STEPS.map((_, i) => (
              <span key={i} className={`tour-step-dot ${i === index ? 'is-active' : ''}`} />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {index > 0 && (
              <button type="button" onClick={() => setIndex((i) => Math.max(0, i - 1))} className="btn btn-secondary btn-sm">上一步</button>
            )}
            <button
              type="button"
              onClick={() => (isLast ? finish() : setIndex((i) => i + 1))}
              className="btn btn-primary btn-sm"
            >
              {isLast ? '开始使用' : '下一步'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
