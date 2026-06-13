export type ReplayClockState = {
  realDate: Date;
  realTimestampLabel: string;
  replayMinuteOfDay: number;
  replayClockLabel: string;
};

export function getReplayMinuteOfDay(date: Date) {
  return date.getHours() * 60 + date.getMinutes();
}

export function formatReplayClock(minutes: number) {
  const safeMinutes = ((minutes % 1440) + 1440) % 1440;
  const hour = Math.floor(safeMinutes / 60);
  const minute = safeMinutes % 60;
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

export function buildReplayClockState(date = new Date()): ReplayClockState {
  return {
    realDate: date,
    realTimestampLabel: date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }),
    replayMinuteOfDay: getReplayMinuteOfDay(date),
    replayClockLabel: formatReplayClock(getReplayMinuteOfDay(date)),
  };
}

export function pickReplayIndex(total: number, minuteOfDay: number) {
  if (total <= 1) return 0;
  const ratio = Math.max(0, Math.min(1, minuteOfDay / 1440));
  return Math.min(total - 1, Math.floor(ratio * total));
}

export function pickReplayItemByIndex<T>(items: T[], minuteOfDay: number) {
  if (!items.length) return { item: null as T | null, index: -1, total: 0, slotMinutes: 1440 };
  const index = pickReplayIndex(items.length, minuteOfDay);
  return {
    item: items[index] ?? items[0],
    index,
    total: items.length,
    slotMinutes: Math.max(1, Math.round(1440 / items.length)),
  };
}

export function pickReplayItemBySlot<T extends { replay_slot_start_minute?: number | null }>(items: T[], minuteOfDay: number) {
  if (!items.length) return { item: null as T | null, index: -1, total: 0, slotMinutes: 1440 };
  const sorted = [...items].sort(
    (a, b) => (a.replay_slot_start_minute ?? 0) - (b.replay_slot_start_minute ?? 0),
  );
  let index = sorted.findIndex((item, currentIndex) => {
    const start = item.replay_slot_start_minute ?? 0;
    const next = sorted[currentIndex + 1]?.replay_slot_start_minute ?? 1440;
    return minuteOfDay >= start && minuteOfDay < next;
  });
  if (index < 0) {
    index = minuteOfDay < (sorted[0]?.replay_slot_start_minute ?? 0) ? 0 : sorted.length - 1;
  }
  return {
    item: sorted[index] ?? sorted[0],
    index,
    total: sorted.length,
    slotMinutes: Math.max(1, Math.round(1440 / sorted.length)),
    sorted,
  };
}
