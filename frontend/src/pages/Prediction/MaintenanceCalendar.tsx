import { useState, useMemo, useCallback, useEffect } from 'react';
import { rulColor } from '../../hooks/useECharts';
import api from '../../services/api';
import type { RULPrediction, WorkOrder } from '../../types';

// ── Types ──
interface ScheduledTask {
  turbine_id: number; turbine_name: string; region: string; component: string;
  rul_days: number; hi_value: number; urgency_score: number; priority: string;
  action: string; downtime_hours: number; crew_size: number;
  parts_needed: string[]; cost_estimate: number;
  scheduled_date?: string; time_slot?: string; overflow?: boolean;
}

interface Conflict {
  date: string | null; type: string; severity: string; message: string;
  items?: string[]; suggestion?: string;
}

interface WeatherDay {
  date: string; score: number; safe: boolean; flags: string[];
}

type ViewMode = 'month' | 'week' | 'day';

// ── Helpers ──
const DAY_NAMES = ['一', '二', '三', '四', '五', '六', '日'];
const MONTH_NAMES = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];

function dateKey(d: Date) { const m = d.getMonth() + 1; return `${d.getFullYear()}-${m < 10 ? '0' + m : m}-${d.getDate() < 10 ? '0' + d.getDate() : d.getDate()}`; }
function sameDay(a: Date, b: Date) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }

function weatherEmoji(score: number) { return score >= 80 ? '☀️' : score >= 50 ? '⛅' : score >= 30 ? '🌧️' : '⛈️'; }
function weatherBg(score: number) { return score < 30 ? 'bg-accent-red/5' : score < 50 ? 'bg-accent-yellow/5' : ''; }

// ── Props ──
interface Props {
  workOrders: WorkOrder[];
  rulItems: RULPrediction[];
  turbines: { id: number; name: string; region: string; lat?: number | null; lng?: number | null }[];
  scheduledTasks: ScheduledTask[];
  conflicts: Conflict[];
  onAutoSchedule: () => void;
  onScheduleItem: (task: ScheduledTask, date: Date) => void;
  scheduling: boolean;
}

// ═══════════════════════════════════════════════════════════════
export default function MaintenanceCalendar({
  workOrders, rulItems, turbines, scheduledTasks, conflicts,
  onAutoSchedule, onScheduleItem, scheduling,
}: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('month');
  const [cursor, setCursor] = useState(new Date()); // navigate month/week
  const [selectedDate, setSelectedDate] = useState<Date | null>(new Date());
  const [tooltip, setTooltip] = useState<{ x: number; y: number; date: Date } | null>(null);
  const [weather, setWeather] = useState<WeatherDay[]>([]);

  // Load weather
  useEffect(() => {
    api.get('/prediction/weather-windows', { params: { days: 60, lat: 37.3, lng: 107.6 } })
      .then(r => setWeather(r.data.windows || []))
      .catch(() => {});
  }, []);

  // ── Derived data ──
  const today = new Date();

  // RUL estimated dates
  const rulDates = useMemo(() => {
    const now = Date.now();
    return rulItems.map(p => ({ ...p, est: new Date(now + p.remaining_life_days * 86400000) }));
  }, [rulItems]);

  // Build date → events lookup
  const eventMap = useMemo(() => {
    const m = new Map<string, { wos: WorkOrder[]; ruls: (RULPrediction & { est: Date })[]; tasks: ScheduledTask[]; conflicts: Conflict[] }>();
    for (const wo of workOrders) {
      const ref = wo.due_date ? new Date(wo.due_date) : new Date(wo.created_at);
      const k = dateKey(ref); const e = m.get(k) || { wos: [], ruls: [], tasks: [], conflicts: [] };
      e.wos.push(wo); m.set(k, e);
    }
    for (const r of rulDates) {
      const k = dateKey(r.est); const e = m.get(k) || { wos: [], ruls: [], tasks: [], conflicts: [] };
      e.ruls.push(r); m.set(k, e);
    }
    for (const t of scheduledTasks) {
      if (t.scheduled_date) {
        const k = t.scheduled_date; const e = m.get(k) || { wos: [], ruls: [], tasks: [], conflicts: [] };
        e.tasks.push(t); m.set(k, e);
      }
    }
    for (const c of conflicts) {
      if (c.date) {
        const k = c.date; const e = m.get(k) || { wos: [], ruls: [], tasks: [], conflicts: [] };
        e.conflicts.push(c); m.set(k, e);
      }
    }
    return m;
  }, [workOrders, rulDates, scheduledTasks, conflicts]);

  const getEvents = useCallback((d: Date) => eventMap.get(dateKey(d)) || { wos: [], ruls: [], tasks: [], conflicts: [] }, [eventMap]);
  const getWeather = useCallback((d: Date) => weather.find(w => w.date === d.toISOString().slice(0, 10)), [weather]);

  // ── Navigation ──
  const nav = (dir: number) => {
    const c = new Date(cursor);
    if (viewMode === 'month') c.setMonth(c.getMonth() + dir);
    else if (viewMode === 'week') c.setDate(c.getDate() + dir * 7);
    else c.setDate(c.getDate() + dir);
    setCursor(c);
  };

  const title = viewMode === 'month' ? `${cursor.getFullYear()}年${MONTH_NAMES[cursor.getMonth()]}` :
    viewMode === 'week' ? `${cursor.getFullYear()}年 第${Math.ceil((cursor.getDate() + new Date(cursor.getFullYear(), cursor.getMonth(), 1).getDay()) / 7)}周` :
    `${cursor.getFullYear()}年${cursor.getMonth() + 1}月${cursor.getDate()}日`;

  // ── Export ICS ──
  const handleExport = () => {
    const token = localStorage.getItem('token');
    if (token) {
      const a = document.createElement('a');
      a.href = `/api/prediction/schedule/export-ics?token=${token}`;
      a.download = 'fengdiao_schedule.ics';
      a.click();
    }
  };

  // ── Day cell color ──
  const dayCellClass = (d: Date, events: ReturnType<typeof getEvents>) => {
    let cls = 'bg-bg-secondary p-1 cursor-pointer transition-colors hover:bg-bg-hover relative min-h-[50px]';
    const w = getWeather(d);
    if (w && !w.safe) cls += ` ${weatherBg(w.score)}`;
    if (sameDay(d, today)) cls += ' ring-1 ring-accent-blue';
    if (selectedDate && sameDay(d, selectedDate)) cls += ' ring-1 ring-accent-purple';
    if (events.conflicts.some(c => c.severity === 'error')) cls += ' bg-accent-red/10';
    return cls;
  };

  // ── Render ──
  return (
    <div className="bg-bg-card border border-border-default rounded-lg p-4 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium">运维日历</h3>
          {/* View switcher */}
          <div className="flex rounded border border-border-default overflow-hidden text-[10px]">
            {(['month', 'week', 'day'] as ViewMode[]).map(v => (
              <button key={v} onClick={() => setViewMode(v)}
                className={`px-2 py-0.5 ${viewMode === v ? 'bg-accent-blue text-white' : 'text-text-muted hover:text-text-primary'}`}>
                {v === 'month' ? '月' : v === 'week' ? '周' : '日'}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs">
          <button onClick={() => nav(-1)} className="px-1.5 py-0.5 hover:text-accent-blue">◀</button>
          <span className="font-medium min-w-[80px] text-center">{title}</span>
          <button onClick={() => nav(1)} className="px-1.5 py-0.5 hover:text-accent-blue">▶</button>
          <button onClick={() => setCursor(new Date())} className="ml-2 px-2 py-0.5 border border-border-default rounded text-[9px] hover:border-accent-blue">今天</button>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={onAutoSchedule} disabled={scheduling}
            className="px-2 py-0.5 bg-accent-blue/20 border border-accent-blue/30 rounded text-[9px] text-accent-blue hover:bg-accent-blue/30 disabled:opacity-50">
            {scheduling ? '排程中...' : '🤖 自动排程'}
          </button>
          <button onClick={handleExport} className="px-2 py-0.5 border border-border-default rounded text-[9px] text-text-muted hover:text-accent-blue">📅 导出ICS</button>
        </div>
      </div>

      {/* Conflict summary */}
      {conflicts.length > 0 && (
        <div className="mb-2 p-1.5 bg-accent-red/5 border border-accent-red/20 rounded text-[9px]">
          {conflicts.filter(c => c.severity === 'error').map(c => <p key={c.message} className="text-accent-red">⚠ {c.message} — {c.suggestion}</p>)}
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-3 mb-1 text-[9px] text-text-muted flex-wrap">
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-red mr-1"/>紧急</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-blue mr-1"/>工单</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-green mr-1"/>RUL计划</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-accent-purple mr-1"/>已排程</span>
        <span><span title="天气风险">☀️/⛈️ 天气</span></span>
      </div>

      {/* ── Month View ── */}
      {viewMode === 'month' && <MonthGrid cursor={cursor} today={today} selectedDate={selectedDate} getEvents={getEvents} getWeather={getWeather} dayCellClass={dayCellClass} onHover={setTooltip} onClick={setSelectedDate} />}

      {/* ── Week View ── */}
      {viewMode === 'week' && <WeekGrid cursor={cursor} today={today} selectedDate={selectedDate} getEvents={getEvents} getWeather={getWeather} onSelect={setSelectedDate} turbines={turbines} />}

      {/* ── Day View ── */}
      {viewMode === 'day' && selectedDate && <DayView date={selectedDate} events={getEvents(selectedDate)} weather={getWeather(selectedDate)} turbines={turbines} />}

      {/* Hover tooltip */}
      {tooltip && viewMode === 'month' && (
        <div className="fixed z-[999] bg-bg-card border border-border-default rounded-lg shadow-xl p-2 min-w-[220px] max-w-[300px] pointer-events-none"
          style={{ left: tooltip.x + 8, top: tooltip.y }}>
          <p className="text-[10px] font-medium mb-1 border-b pb-1">{tooltip.date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</p>
          {getEvents(tooltip.date).conflicts.map(c => <p key={c.message} className="text-[9px] text-accent-red">⚠ {c.message}</p>)}
          {getEvents(tooltip.date).tasks.map(t => <p key={`t-${t.turbine_id}-${t.component}`} className="text-[9px] text-accent-purple">🔧 {t.time_slot} {t.turbine_name} {t.component} {t.action}</p>)}
          {getEvents(tooltip.date).wos.map(w => <p key={`w-${w.id}`} className="text-[9px]">📋 WO-{String(w.id).padStart(4, '0')} {w.title}</p>)}
          {getEvents(tooltip.date).ruls.filter(r => r.remaining_life_days < 90).map(r => <p key={`r-${r.turbine_id}-${r.component}`} className="text-[9px] text-accent-yellow">⏰ {r.turbine_name} {r.component} RUL{r.remaining_life_days.toFixed(0)}天</p>)}
        </div>
      )}
    </div>
  );
}

// ── Month Grid ──
function MonthGrid({ cursor, today, selectedDate, getEvents, getWeather, dayCellClass, onHover, onClick }: any) {
  const y = cursor.getFullYear(); const m = cursor.getMonth();
  const firstDay = new Date(y, m, 1).getDay();
  const daysInMonth = new Date(y, m + 1, 0).getDate();
  const startOffset = firstDay === 0 ? 6 : firstDay - 1;

  return (
    <>
      <div className="grid grid-cols-7 text-center text-[9px] text-text-muted mb-0.5">{DAY_NAMES.map(d => <div key={d} className="py-0.5">{d}</div>)}</div>
      <div className="grid grid-cols-7 gap-px bg-border-default rounded overflow-hidden flex-1">
        {Array.from({ length: startOffset }).map((_, i) => <div key={`e${i}`} className="bg-bg-secondary min-h-[50px]"/>)}
        {Array.from({ length: daysInMonth }).map((_, i) => {
          const d = new Date(y, m, i + 1); const ev = getEvents(d); const w = getWeather(d);
          const isToday = sameDay(d, today);
          return (
            <div key={i} className={dayCellClass(d, ev)}
              onMouseEnter={e => { if (ev.wos.length + ev.ruls.length + ev.tasks.length > 0) { const r = (e.target as HTMLElement).getBoundingClientRect(); onHover({ x: r.right, y: r.top, date: d }); }}}
              onMouseLeave={() => onHover(null)}
              onClick={() => onClick(d)}>
              <div className="flex items-center justify-between">
                <span className={`text-[10px] ${isToday ? 'text-accent-blue font-bold' : 'text-text-secondary'}`}>{i + 1}</span>
                {w && <span className="text-[8px]" title={`${w.score}分 ${w.flags.join(',')}`}>{weatherEmoji(w.score)}</span>}
              </div>
              <div className="flex flex-wrap gap-0.5 mt-0.5">
                {ev.conflicts.filter(c => c.severity === 'error').length > 0 && <span className="w-2 h-2 rounded-sm bg-accent-red"/>}
                {ev.tasks.length > 0 && <span className="w-2 h-2 rounded-full bg-accent-purple"/>}
                {ev.wos.filter((w: WorkOrder) => w.status === 'pending').length > 0 && <span className="w-2 h-2 rounded-full bg-accent-red"/>}
                {ev.wos.length > 0 && <span className="w-2 h-2 rounded-full bg-accent-blue"/>}
                {ev.ruls.filter((r: any) => r.remaining_life_days < 30).length > 0 && <span className="w-2 h-2 rounded-full bg-accent-red"/>}
                {ev.ruls.filter((r: any) => r.remaining_life_days >= 30 && r.remaining_life_days < 90).length > 0 && <span className="w-2 h-2 rounded-full bg-accent-yellow"/>}
                {ev.ruls.filter((r: any) => r.remaining_life_days >= 90).length > 0 && <span className="w-2 h-2 rounded-full bg-accent-green"/>}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ── Week Grid ──
function WeekGrid({ cursor, today, selectedDate, getEvents, getWeather, onSelect, turbines }: any) {
  // Find Monday of cursor's week
  const day = cursor.getDay(); const mondayOffset = day === 0 ? -6 : 1 - day;
  const monday = new Date(cursor); monday.setDate(cursor.getDate() + mondayOffset);

  const days = Array.from({ length: 7 }).map((_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return d; });

  const hours = Array.from({ length: 10 }).map((_, i) => i + 8); // 8am-5pm

  return (
    <div className="flex-1 overflow-auto">
      <div className="grid grid-cols-8 gap-px bg-border-default rounded overflow-hidden" style={{ minWidth: 600 }}>
        {/* Header row */}
        <div className="bg-bg-secondary p-1 text-center text-[9px] text-text-muted">时间</div>
        {days.map(d => {
          const isToday = sameDay(d, today); const isSel = selectedDate && sameDay(d, selectedDate);
          const w = getWeather(d);
          return (
            <div key={d.toISOString()} onClick={() => onSelect(d)} className={`bg-bg-secondary p-1 text-center cursor-pointer hover:bg-bg-hover ${isToday ? 'ring-1 ring-accent-blue' : ''} ${isSel ? 'ring-1 ring-accent-purple' : ''}`}>
              <p className="text-[10px] font-medium">{DAY_NAMES[d.getDay() === 0 ? 6 : d.getDay() - 1]}</p>
              <p className={`text-[11px] ${isToday ? 'text-accent-blue font-bold' : ''}`}>{d.getDate()}</p>
              {w && <span className="text-[8px]">{weatherEmoji(w.score)}</span>}
            </div>
          );
        })}
        {/* Time slots */}
        {hours.map(h =>
          Array.from({ length: 8 }).map((_, col) => {
            if (col === 0) return <div key={`h-${h}`} className="bg-bg-secondary p-0.5 text-center text-[8px] text-text-muted">{h}:00</div>;
            const d = days[col - 1]; const ev = getEvents(d);
            const tasks = ev.tasks.filter((t: any) => {
              if (!t.time_slot) return false;
              const sh = parseInt(t.time_slot);
              return h >= sh && h < sh + Math.ceil(t.downtime_hours / 4);
            });
            if (tasks.length > 0) return (
              <div key={`${h}-${col}`} className="bg-accent-purple/20 p-0.5 text-[7px] text-accent-purple cursor-pointer" title={tasks.map((t: any) => `${t.turbine_name} ${t.component} ${t.action}`).join('\n')}>
                {tasks[0].turbine_name.slice(0, 6)}…
              </div>
            );
            return <div key={`${h}-${col}`} className="bg-bg-secondary p-0.5"/>;
          })
        )}
      </div>
    </div>
  );
}

// ── Day View ──
function DayView({ date, events, weather, turbines }: {
  date: Date; events: ReturnType<typeof getEventsPrototype>; weather: WeatherDay | undefined; turbines: any[];
}) {
  const hours = Array.from({ length: 12 }).map((_, i) => i + 7); // 7am-6pm
  return (
    <div className="flex-1 overflow-auto">
      <div className="p-2 bg-bg-hover rounded mb-2 text-xs">
        <span className="font-medium">{date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</span>
        {weather && <span className="ml-2 text-text-muted">{weatherEmoji(weather.score)} {weather.score}分 {weather.flags.length > 0 ? `· ${weather.flags.join(', ')}` : ''}</span>}
      </div>
      {/* Conflicts */}
      {events.conflicts.length > 0 && (
        <div className="mb-2 p-2 bg-accent-red/5 border border-accent-red/20 rounded text-[9px]">
          {events.conflicts.map(c => <p key={c.message} className="text-accent-red">⚠ {c.message} — {c.suggestion}</p>)}
        </div>
      )}
      {/* Timeline */}
      <div className="space-y-1">
        {hours.map(h => {
          const slotTasks = events.tasks.filter((t: any) => {
            if (!t.time_slot) return false;
            const sh = parseInt(t.time_slot);
            return h >= sh && h < sh + Math.ceil(t.downtime_hours / 4);
          });
          const slotWos = events.wos.filter((w: any) => new Date(w.created_at).getHours() === h);
          const isBusy = slotTasks.length > 0 || slotWos.length > 0;
          return (
            <div key={h} className={`flex gap-2 items-start py-1 px-2 rounded text-[10px] ${isBusy ? 'bg-accent-purple/10' : ''}`}>
              <span className="w-10 text-text-muted text-right flex-shrink-0">{h}:00</span>
              <div className="flex-1 space-y-0.5">
                {slotTasks.map((t: any) => (
                  <div key={`${t.turbine_id}-${t.component}`} className="px-2 py-1 bg-accent-purple/20 border border-accent-purple/30 rounded text-[9px]">
                    <span className="font-medium text-accent-purple">{t.turbine_name} {t.component}</span>
                    <span className="text-text-muted ml-2">{t.action} · {t.crew_size}人 · ¥{t.cost_estimate.toLocaleString()}</span>
                  </div>
                ))}
                {slotWos.map((w: any) => (
                  <div key={`wo-${w.id}`} className="px-2 py-1 bg-accent-blue/10 border border-accent-blue/20 rounded text-[9px]">
                    📋 WO-{String(w.id).padStart(4, '0')} {w.title}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      {/* RUL deadlines today */}
      {events.ruls.filter((r: any) => r.remaining_life_days < 90).length > 0 && (
        <div className="mt-2 pt-2 border-t border-border-default">
          <p className="text-[9px] text-text-muted mb-1">今日 RUL 预警</p>
          {events.ruls.filter((r: any) => r.remaining_life_days < 90).slice(0, 5).map((r: any) => (
            <p key={`rul-${r.turbine_id}-${r.component}`} className="text-[9px]">
              <span className="font-mono" style={{ color: rulColor(r.remaining_life_days) }}>{r.remaining_life_days.toFixed(0)}天</span>
              <span className="ml-1">{r.turbine_name} {r.component}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// Type helper for DayView
function getEventsPrototype(date: Date) {
  return { wos: [] as any[], ruls: [] as any[], tasks: [] as any[], conflicts: [] as any[] };
}