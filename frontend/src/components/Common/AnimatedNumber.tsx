import { useEffect, useRef, useState } from 'react';

/**
 * KPI 数字计数动画 —— 用 requestAnimationFrame 从旧值缓动到新值。
 * 尊重系统「减少动态效果」偏好：开启时直接跳到目标值。
 */

const prefersReducedMotion = () =>
  typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function useCountUp(target: number, duration = 700): number {
  const [value, setValue] = useState(target);
  const fromRef = useRef(target);
  const rafRef = useRef<number>();

  useEffect(() => {
    if (!Number.isFinite(target)) { setValue(target); return; }
    const from = fromRef.current;
    if (from === target || prefersReducedMotion() || duration <= 0) {
      fromRef.current = target;
      setValue(target);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic —— 与 --ease-out 观感一致
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target, duration]);

  return value;
}

interface AnimatedNumberProps {
  value: number | null | undefined;
  /** 小数位数 */
  decimals?: number;
  /** value 为 null/undefined/NaN 时展示的占位 */
  placeholder?: string;
  duration?: number;
  className?: string;
  style?: React.CSSProperties;
}

export default function AnimatedNumber({
  value,
  decimals = 0,
  placeholder = '--',
  duration = 700,
  className = '',
  style,
}: AnimatedNumberProps) {
  const valid = typeof value === 'number' && Number.isFinite(value);
  const animated = useCountUp(valid ? (value as number) : 0, duration);
  if (!valid) return <span className={className} style={style}>{placeholder}</span>;
  return (
    <span className={className} style={style}>
      {animated.toFixed(decimals)}
    </span>
  );
}
