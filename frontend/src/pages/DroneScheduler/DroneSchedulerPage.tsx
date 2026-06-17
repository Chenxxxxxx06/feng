import { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import api from '../../services/api';
import DroneMap from '../../components/Map/DroneMap';
import { solveTsp, solveVrp } from '../../utils/dronePathPlanner';
import { buildFleet, tickSimulation, createDefaultConfig } from '../../utils/droneSimulator';
import { AStar3DPathPlanner } from '../../utils/aStar3DPathPlanner';
import type { Turbine, Drone, DroneFleetConfig, NoFlyZone } from '../../types';
import type { TspResult, VrpResult } from '../../utils/dronePathPlanner';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import WindFarm3DView from '../../components/Map/three/WindFarm3DView';
import ErrorBoundary from '../../components/Common/ErrorBoundary';
import { useDrone3DStore } from '../../services/drone3dStore';

type Mode = 'tsp' | 'vrp' | 'astar3d';

export default function DroneSchedulerPage() {
  // ── Data ──
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');

  // ── Farm ──
  const [activeFarm, setActiveFarm] = useState<string | null>(null);

  // ── Farms list (derived) ──
  const farms = useMemo(() => {
    const s = new Set<string>();
    turbines.forEach((t) => { if (t.region) s.add(t.region); });
    return Array.from(s).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [turbines]);

  // ── Auto-select first farm once data loads (only on initial load) ──
  const didInitRef = useRef(false);
  useEffect(() => {
    if (didInitRef.current) return;
    if (!activeFarm && farms.length > 0) {
      setActiveFarm(farms[0]);
      didInitRef.current = true;
    }
  }, [farms, activeFarm]);

  // ── Config ──
  const [mode, setMode] = useState<Mode>('vrp');
  const [config, setConfig] = useState<DroneFleetConfig>(createDefaultConfig());
  const [assignmentMode, setAssignmentMode] = useState<'auto' | 'manual'>('auto');

  // ── A* 3D Path Planner ──
  const [cruiseAltitude, setCruiseAltitude] = useState(50);
  const [noFlyZones, setNoFlyZones] = useState<NoFlyZone[]>([]);
  const [addingNoFly, setAddingNoFly] = useState(false);
  const [nfzCorner1, setNfzCorner1] = useState<{ lat: number; lng: number } | null>(null);
  const aStarPlanner = useRef(new AStar3DPathPlanner({ gridResolution: 80 }));

  // ── Fleet ──
  const [drones, setDrones] = useState<Drone[]>([]);
  const [hasPlan, setHasPlan] = useState(false);
  const [selectedDroneId, setSelectedDroneId] = useState<number | null>(null);

  // ── Simulation ──
  const [isRunning, setIsRunning] = useState(false);
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);

  const animRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);

  // ── Fetch turbines ──
  const storeSetTurbines = useDrone3DStore((s) => s.setTurbines);
  useEffect(() => {
    api.get<{ turbines: Turbine[]; total: number; healthy: number; warning: number; faulty: number }>('/turbines/')
      .then(({ data }) => {
        setTurbines(data.turbines);
        storeSetTurbines(data.turbines);
      })
      .catch(() => setMessage('风机数据加载失败'))
      .finally(() => setLoading(false));
  }, [storeSetTurbines]);

  // ── Plan path ──
  const planPath = useCallback((farm: string, m: Mode, cfg: DroneFleetConfig) => {
    const farmTurbines = turbines.filter((t) => t.region === farm);
    if (!farmTurbines.length) { setMessage('该风场无风机数据'); return; }
    const points = farmTurbines.map((t) => ({ lat: t.lat, lng: t.lng, id: t.id, name: t.name }));
    setTotalCount(points.length);
    setCompletedCount(0);
    setElapsedTime(0);
    setIsRunning(false);

    if (m === 'astar3d') {
      // ── A* 3D 路径规划 ──
      if (points.length < 2) { setMessage('至少需要2台风机'); return; }
      aStarPlanner.current.setNoFlyZones(noFlyZones);

      // 使用第一台风机作为起点，按TSP顺序构建3D路径
      const startPoint = points[0];
      const endPoint = points[points.length - 1];
      const result3d = aStarPlanner.current.planFullFlightPath(
        { lat: startPoint.lat, lng: startPoint.lng, altitude: 0 },
        { lat: endPoint.lat, lng: endPoint.lng, altitude: 0 },
        cruiseAltitude,
        { smoothPath: true },
      );

      if (result3d.success && result3d.path.length > 0) {
        // 构建单架无人机的3D飞行任务
        const drone: Drone = {
          id: 1,
          name: 'Drone-A*',
          status: 'idle' as const,
          battery: 100,
          range: cfg.range,
          speed: cfg.speed,
          color: '#39d2c0',
          assignedTurbines: points.map((p) => p.id ?? 0).filter((id) => id > 0),
          completedTurbines: [],
          currentPosition: result3d.path[0] ? { lat: result3d.path[0].lat, lng: result3d.path[0].lng } : null,
          path: result3d.path.map((wp) => ({ lat: wp.lat, lng: wp.lng })),
          progress: 0,
          _altitude: cruiseAltitude,
        };
        setDrones([drone]);
        setHasPlan(true);
        const store = useDrone3DStore.getState();
        store.setDrones([drone]);
        store.setHasPlan(true);
        store.setActiveFarm(farm);
        store.setCruiseAltitude(cruiseAltitude);
        store.setNoFlyZones(noFlyZones);
        const dist = result3d.statistics?.totalDistance ?? 0;
        setMessage(`A* 3D · ${(dist / 1000).toFixed(1)}km · ${result3d.statistics?.totalWaypoints ?? 0}航点 · ${cruiseAltitude}m巡航`);
      } else {
        setMessage(`A* 路径规划失败: ${result3d.error || '未知错误'}`);
      }
      return;
    }

    // ── 传统 TSP/VRP 2D 规划 ──
    const result: TspResult | VrpResult = (m === 'tsp' || cfg.count <= 1)
      ? solveTsp(points)
      : solveVrp(points, cfg.count);
    const fleet = buildFleet(result, cfg, farm);
    // 为所有无人机设置默认高度
    fleet.forEach((d) => { d._altitude = cruiseAltitude; });
    setDrones(fleet);
    setHasPlan(true);
    const store = useDrone3DStore.getState();
    store.setDrones(fleet);
    store.setHasPlan(true);
    store.setActiveFarm(farm);
    store.setCruiseAltitude(cruiseAltitude);
    store.setNoFlyZones(noFlyZones);
    const dist = 'assignments' in result ? result.totalDistance : result.totalDistance;
    setMessage(`${m === 'tsp' ? '单机' : `${cfg.count}机分区`} · ${dist.toLocaleString()}m · ${points.length}台风机`);
  }, [turbines, cruiseAltitude, noFlyZones]);

  useEffect(() => {
    if (!activeFarm) { setHasPlan(false); setDrones([]); setIsRunning(false); return; }
    if (isRunning) {
      // ── 运行中不重置仿真，只在线更新速度和续航 ──
      setDrones((prev) => prev.map((d) => ({ ...d, speed: config.speed, range: config.range, _altitude: cruiseAltitude })));
      useDrone3DStore.getState().setCruiseAltitude(cruiseAltitude);
      useDrone3DStore.getState().setNoFlyZones(noFlyZones);
      return;
    }
    planPath(activeFarm, mode, config);
  }, [activeFarm, mode, config, cruiseAltitude, noFlyZones]);

  const handleReplan = () => { if (activeFarm) planPath(activeFarm, mode, config); };

  // ── Map click for no-fly zone ──
  const handleMapClick = useCallback((latlng: { lat: number; lng: number }) => {
    if (!addingNoFly) return;
    if (!nfzCorner1) {
      setNfzCorner1(latlng);
      setMessage('已选第一个角点，请点击地图选第二个角点');
    } else {
      // Second corner — create the zone
      const south_lat = Math.min(nfzCorner1.lat, latlng.lat);
      const north_lat = Math.max(nfzCorner1.lat, latlng.lat);
      const west_lng = Math.min(nfzCorner1.lng, latlng.lng);
      const east_lng = Math.max(nfzCorner1.lng, latlng.lng);
      const newZone: NoFlyZone = {
        name: `禁飞区 ${noFlyZones.length + 1}`,
        south_lat, north_lat, west_lng, east_lng,
        min_altitude: 0,
        max_altitude: cruiseAltitude + 50,
      };
      const updated = [...noFlyZones, newZone];
      setNoFlyZones(updated);
      setNfzCorner1(null);
      setAddingNoFly(false);
      useDrone3DStore.getState().setNoFlyZones(updated);
      setMessage(`禁飞区已添加: ${newZone.name}`);
    }
  }, [addingNoFly, nfzCorner1, noFlyZones, cruiseAltitude]);

  // ── Manual assignment: click turbine → assign to selected drone ──
  const handleTurbineClick = useCallback((turbine: Turbine) => {
    if (assignmentMode !== 'manual' || !selectedDroneId) return;
    setDrones((prev) => prev.map((d) => {
      if (d.id !== selectedDroneId) return d;
      // Toggle: remove if already assigned, add if not
      const already = d.assignedTurbines.includes(turbine.id);
      if (already) {
        return {
          ...d,
          assignedTurbines: d.assignedTurbines.filter((id) => id !== turbine.id),
          path: d.path.filter((_, i) => i === 0 || d.assignedTurbines[i] !== turbine.id),
        };
      }
      // Remove from other drones first, then add to this one
      const newAssigned = [...d.assignedTurbines, turbine.id];
      // Recompute TSP for this drone
      const points = [
        { lat: d.path[0]?.lat || turbine.lat, lng: d.path[0]?.lng || turbine.lng },
        ...newAssigned.map((id) => {
          const t = turbines.find((tt) => tt.id === id);
          return { lat: t?.lat || 0, lng: t?.lng || 0, id: t?.id, name: t?.name };
        }),
      ];
      const tsp = solveTsp(points);
      return {
        ...d,
        assignedTurbines: newAssigned,
        path: tsp.path.map((p) => ({ lat: p.lat, lng: p.lng })),
        completedTurbines: d.completedTurbines.filter((id) => newAssigned.includes(id)),
      };
    }));
    // Also remove from other drones
    setDrones((prev) => prev.map((d) => {
      if (d.id === selectedDroneId) return d;
      if (!d.assignedTurbines.includes(turbine.id)) return d;
      const newAssigned = d.assignedTurbines.filter((id) => id !== turbine.id);
      const startPt = d.path[0];
      const points = [
        { lat: startPt?.lat || 0, lng: startPt?.lng || 0 },
        ...newAssigned.map((id) => {
          const t = turbines.find((tt) => tt.id === id);
          return { lat: t?.lat || 0, lng: t?.lng || 0, id: t?.id, name: t?.name };
        }),
      ];
      const tsp = newAssigned.length > 0 ? solveTsp(points) : { path: startPt ? [{ lat: startPt.lat, lng: startPt.lng }] : [], totalDistance: 0, iterations: 0 };
      return {
        ...d,
        assignedTurbines: newAssigned,
        path: tsp.path.map((p) => ({ lat: p.lat, lng: p.lng })),
        completedTurbines: d.completedTurbines.filter((id) => newAssigned.includes(id)),
      };
    }));
  }, [assignmentMode, selectedDroneId, turbines]);

  // ── Simulation tick ──
  const tickRef = useRef<() => void>(() => {});
  tickRef.current = () => {
    const now = performance.now();
    const dt = lastTickRef.current ? (now - lastTickRef.current) / 1000 : 0.05;
    lastTickRef.current = now;
    const clampedDt = Math.min(dt, 0.2);
    setDrones((prev) => {
      const { fleet, allComplete, completedThisTick } = tickSimulation(prev, clampedDt, speedMultiplier);
      if (completedThisTick > 0) setCompletedCount((c) => c + completedThisTick);
      if (allComplete) { setIsRunning(false); setMessage('全部风机已拍摄完成！'); }
      useDrone3DStore.getState().setDrones(fleet);
      return fleet;
    });
    setElapsedTime((t) => t + clampedDt * speedMultiplier);
    animRef.current = requestAnimationFrame(() => tickRef.current());
  };

  useEffect(() => {
    if (isRunning && drones.length > 0) {
      lastTickRef.current = 0;
      animRef.current = requestAnimationFrame(() => tickRef.current());
    }
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [isRunning, drones.length]);

  // ── Derived ──
  const farmTurbineCount = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm).length : 0,
    [activeFarm, turbines],
  );

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, '0')}`;
  };

  // ── Render ──
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        <span className="animate-pulse">加载风机数据...</span>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: 'radial-gradient(ellipse at 50% 30%, #0f1a2e 0%, #080c12 70%)' }}>
      {/* ── Top Bar ── */}
      <div className="flex-shrink-0 px-6 py-3 flex items-center justify-between border-b border-border-subtle">
        <div className="flex items-center gap-4">
          <h2 className="text-base font-bold tracking-wide">
            <span className="gradient-text">无人机调度 · 数据获取</span>
          </h2>
          <span className="text-[10px] text-text-muted bg-bg-card border border-border-subtle rounded-full px-2.5 py-0.5">
            共 {turbines.length} 台风机
          </span>
          {/* ── Farm selector dropdown ── */}
          {farms.length > 0 && (
            <div className="relative">
              <select
                value={activeFarm || ''}
                onChange={(e) => {
                  const farm = e.target.value || null;
                  setActiveFarm(farm);
                  useDrone3DStore.getState().setActiveFarm(farm);
                }}
                className="appearance-none text-[11px] text-accent-blue bg-accent-blue/10 border border-accent-blue/30 rounded-full px-3 py-1 pr-7 cursor-pointer hover:bg-accent-blue/15 transition-colors focus:outline-none focus:border-accent-blue/60"
              >
                {farms.map((f) => (
                  <option key={f} value={f} style={{ background: '#0f1a2e', color: '#dbeafe' }}>
                    📍 {f}
                  </option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-accent-blue text-[10px]">▾</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {message && <span className="text-[10px] text-text-muted">{message}</span>}
          <span className={`flex items-center gap-1.5 text-[11px] ${hasPlan ? 'text-accent-blue' : 'text-text-muted'}`}>
            <span className={`w-2 h-2 rounded-full ${hasPlan ? 'status-dot-live' : ''}`} style={{ background: hasPlan ? '#388bfd' : '#54657e' }} />
            {hasPlan ? '路径已规划' : '加载风场数据...'}
          </span>
        </div>
      </div>

      {/* ── KPI Strip ── */}
      <div className="flex-shrink-0 px-6 py-3">
        <div className="grid grid-cols-5 gap-3">
          <KPICard label="风机总数" value={String(turbines.length)} unit="台" color="#388bfd" />
          <KPICard label="当前风场" value={activeFarm ? String(farmTurbineCount) : '--'} unit="台" color="#39d2c0" />
          <KPICard label="无人机" value={String(drones.length || config.count)} unit="架" color="#a371f7" />
          <KPICard label="已拍摄" value={hasPlan ? `${completedCount}/${totalCount}` : '--'} unit="" color="#3fb950" />
          <KPICard label="飞行时间" value={isRunning ? formatTime(elapsedTime) : '--'} unit="" color="#f0883e" />
        </div>
      </div>

      {/* ── MAIN: 3-Panel Layout (2D | 3D | 控制台) ── */}
      <div className="flex-1 mx-6 mb-3 flex gap-2 min-h-0">
        {/* 左: 2D Leaflet 地图 */}
        <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle relative" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <div style={{ position: 'absolute', inset: 0 }}>
            <DroneMap
              turbines={turbines}
              drones={drones}
              activeFarm={activeFarm}
              onFarmSelect={setActiveFarm}
              onTurbineClick={handleTurbineClick}
              onMapClick={handleMapClick}
              showPaths={hasPlan}
              manualMode={assignmentMode === 'manual'}
              selectedDroneId={selectedDroneId}
              noFlyZones={noFlyZones}
            />
          </div>
        </div>

        {/* 中: 3D Three.js 视图 */}
        <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle relative" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <ErrorBoundary fallback={
            <div className="flex items-center justify-center h-full text-text-muted" style={{ background: '#071A35' }}>
              <div className="text-center">
                <p className="text-sm">3D 视图加载失败</p>
                <p className="text-xs mt-1">请检查浏览器是否支持 WebGL</p>
              </div>
            </div>
          }>
            <WindFarm3DView />
          </ErrorBoundary>
        </div>

        {/* 右: 无人机调度控制台 (始终可见) */}
        <div className="w-[340px] flex-shrink-0 flex flex-col rounded-xl border border-border-subtle bg-bg-secondary/95 backdrop-blur overflow-hidden">
          {/* Panel Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border-subtle">
            <div>
              <h3 className="font-bold text-sm">无人机调度控制台</h3>
              <p className="text-[10px] text-text-muted">{activeFarm?.replace('陕北', '') || '选择风场'} · {farmTurbineCount}台风机</p>
            </div>
          </div>

          {/* Panel Body */}
          <div className="flex-1 overflow-auto p-4 space-y-3">


            {/* Mode */}
            <div className="industrial-card rounded-lg p-3">
              <h4 className="text-xs font-medium text-text-secondary mb-2">规划模式</h4>
              <div className="flex gap-1.5">
                {(['tsp', 'vrp', 'astar3d'] as Mode[]).map((m) => (
                  <button key={m} onClick={() => setMode(m)}
                    className={`flex-1 rounded-md border px-2 py-2 text-[10px] transition-colors ${
                      mode === m ? 'border-accent-blue/50 bg-accent-blue/10 text-accent-blue' : 'border-border-default text-text-secondary hover:border-accent-blue/40'
                    }`}>
                    {m === 'tsp' ? '单机TSP' : m === 'vrp' ? '多机VRP' : 'A* 3D'}
                  </button>
                ))}
              </div>
            </div>

            {/* Fleet Config */}
            <div className="industrial-card rounded-lg p-3">
              <h4 className="text-xs font-medium text-text-secondary mb-2">机队配置</h4>
              <div className="space-y-2">
                <SliderRow label="无人机数量" value={config.count} min={1} max={8} step={1} unit="架"
                  onChange={(v) => setConfig({ ...config, count: v })} />
                <SliderRow label="单机续航" value={Math.round(config.range / 1000)} min={5} max={100} step={5} unit="km"
                  onChange={(v) => setConfig({ ...config, range: v * 1000 })} />
                <SliderRow label="飞行速度" value={config.speed} min={5} max={30} step={1} unit="m/s"
                  onChange={(v) => setConfig({ ...config, speed: v })} />
              </div>
            </div>

            {/* Cruise Altitude (A* 3D only) */}
            <div className="industrial-card rounded-lg p-3">
              <h4 className="text-xs font-medium text-text-secondary mb-2">
                🛫 巡航高度 <span className="text-accent-blue">{cruiseAltitude}m</span>
              </h4>
              <input type="range" min={20} max={300} step={10} value={cruiseAltitude}
                onChange={(e) => { setCruiseAltitude(Number(e.target.value)); useDrone3DStore.getState().setCruiseAltitude(Number(e.target.value)); }}
                className="w-full accent-blue-500 h-1.5" />
              <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                <span>20m (低空)</span><span>300m (高空)</span>
              </div>
            </div>

            {/* No-Fly Zones */}
            <div className="industrial-card rounded-lg p-3">
              <h4 className="text-xs font-medium text-text-secondary mb-2">
                🚫 禁飞区 ({noFlyZones.length})
              </h4>
              <div className="flex gap-2 mb-2">
                <button
                  onClick={() => { setAddingNoFly(!addingNoFly); setNfzCorner1(null); }}
                  className={`flex-1 rounded-md border px-2 py-1.5 text-[10px] transition-colors ${
                    addingNoFly ? 'border-red-400/50 bg-red-400/10 text-red-400' : 'border-border-default text-text-secondary hover:border-accent-blue/40'
                  }`}>
                  {addingNoFly ? '取消选区' : '➕ 框选禁飞区'}
                </button>
                <button onClick={() => { setNoFlyZones([]); useDrone3DStore.getState().setNoFlyZones([]); }}
                  className="rounded-md border border-border-default px-2 py-1.5 text-[10px] text-text-muted hover:text-red-400 transition-colors">
                  清空
                </button>
              </div>
              {addingNoFly && (
                <p className="text-[10px] text-accent-yellow mb-1">
                  {nfzCorner1 ? '📍 点击地图选第二个角点' : '📍 点击地图选第一个角点'}
                </p>
              )}
              {/* No-fly zone list */}
              {noFlyZones.length > 0 && (
                <div className="space-y-1 max-h-24 overflow-y-auto">
                  {noFlyZones.map((zone, i) => (
                    <div key={i} className="flex items-center justify-between text-[10px] bg-red-400/5 border border-red-400/15 rounded px-2 py-1">
                      <span className="text-text-secondary truncate flex-1">{zone.name}</span>
                      <span className="text-text-muted mx-1">{zone.min_altitude}-{zone.max_altitude}m</span>
                      <button onClick={() => {
                        const newZones = noFlyZones.filter((_, j) => j !== i);
                        setNoFlyZones(newZones);
                        useDrone3DStore.getState().setNoFlyZones(newZones);
                      }}
                        className="text-red-400 hover:text-red-300 ml-1">✕</button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Assignment */}
            <div className="industrial-card rounded-lg p-3">
              <h4 className="text-xs font-medium text-text-secondary mb-2">分配方式</h4>
              <div className="flex gap-2 mb-2">
                {(['auto', 'manual'] as const).map((a) => (
                  <button key={a} onClick={() => setAssignmentMode(a)}
                    className={`flex-1 rounded-md border px-3 py-2 text-xs transition-colors ${
                      assignmentMode === a ? 'border-accent-blue/50 bg-accent-blue/10 text-accent-blue' : 'border-border-default text-text-secondary hover:border-accent-blue/40'
                    }`}>
                    {a === 'auto' ? '自动分区' : '手动分配'}
                  </button>
                ))}
              </div>
              {assignmentMode === 'manual' && (
                <div className="space-y-1">
                  <p className="text-[10px] text-text-muted">点选无人机后在地图上选风机：</p>
                  <div className="flex flex-wrap gap-1">
                    {drones.map((d) => (
                      <button key={d.id} onClick={() => setSelectedDroneId(selectedDroneId === d.id ? null : d.id)}
                        className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                          selectedDroneId === d.id
                            ? 'border-accent-yellow/50 bg-accent-yellow/10 text-accent-yellow'
                            : 'border-border-default text-text-secondary hover:border-accent-blue/40'
                        }`}
                        style={{ borderLeftColor: d.color, borderLeftWidth: 3 }}>
                        {d.name} ({d.assignedTurbines.length}台)
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Plan Button */}
            <button onClick={handleReplan}
              className="w-full rounded-lg py-2 text-sm font-medium transition-all"
              style={{ background: 'rgba(56,139,253,0.1)', border: '1px solid rgba(56,139,253,0.3)', color: '#388bfd' }}>
              重新规划路径
            </button>

            {/* Drone Status */}
            {drones.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-xs font-medium text-text-secondary">无人机状态</h4>
                {drones.map((drone) => (
                  <div key={drone.id} className="industrial-card rounded-lg p-2.5"
                    style={{ borderLeftColor: drone.color, borderLeftWidth: 3, borderLeftStyle: 'solid' }}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium" style={{ color: drone.color }}>{drone.name}</span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
                        drone.status === 'flying' ? 'bg-accent-blue/10 text-accent-blue border border-accent-blue/20' :
                        drone.status === 'returning' ? 'bg-accent-green/10 text-accent-green border border-accent-green/20' :
                        'bg-bg-hover text-text-muted border border-border-subtle'
                      }`}>
                        {drone.status === 'flying' ? '任务中' : drone.status === 'returning' ? '返航' : '空闲'}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-[10px] text-text-muted">
                      <span>📸 {drone.completedTurbines.length}/{drone.assignedTurbines.length}</span>
                      <span>🔋 {drone.battery.toFixed(0)}%</span>
                    </div>
                    <div className="mt-1 h-1 rounded-full bg-bg-hover overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-300" style={{
                        width: `${drone.assignedTurbines.length ? (drone.completedTurbines.length / drone.assignedTurbines.length) * 100 : 0}%`,
                        backgroundColor: drone.color,
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Simulation Controls */}
            {hasPlan && drones.length > 0 && (
              <div className="industrial-card rounded-lg p-3">
                <h4 className="text-xs font-medium text-text-secondary mb-2">模拟控制</h4>
                <div className="flex gap-2 mb-2">
                  {!isRunning ? (
                    <button onClick={() => { setIsRunning(true); useDrone3DStore.getState().setIsRunning(true); }}
                      className="flex-1 rounded-md py-1.5 text-xs font-medium transition-all"
                      style={{ background: 'rgba(63,185,80,0.1)', border: '1px solid rgba(63,185,80,0.3)', color: '#3fb950' }}>
                      ▶ 执行
                    </button>
                  ) : (
                    <button onClick={() => { setIsRunning(false); useDrone3DStore.getState().setIsRunning(false); }}
                      className="flex-1 rounded-md py-1.5 text-xs font-medium transition-all"
                      style={{ background: 'rgba(210,153,34,0.1)', border: '1px solid rgba(210,153,34,0.3)', color: '#d29922' }}>
                      ⏸ 暂停
                    </button>
                  )}
                  <button onClick={handleReplan}
                    className="rounded-md border border-border-default px-2 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors">
                    ↺ 重置
                  </button>
                </div>
                <div className="flex gap-1">
                  {[1, 2, 4, 8].map((spd) => (
                    <button key={spd} onClick={() => { setSpeedMultiplier(spd); useDrone3DStore.getState().setSpeedMultiplier(spd); }}
                      className={`flex-1 rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                        speedMultiplier === spd ? 'border-accent-blue/50 bg-accent-blue/10 text-accent-blue' : 'border-border-default text-text-muted hover:border-accent-blue/30'
                      }`}>{spd}×</button>
                  ))}
                </div>
                {isRunning && (
                  <div className="mt-2">
                    <div className="flex justify-between text-[10px] text-text-muted mb-1">
                      <span>拍摄进度</span><span>{completedCount}/{totalCount}</span>
                    </div>
                    <div className="h-1.5 rounded-full bg-bg-hover overflow-hidden">
                      <div className="h-full bg-accent-blue transition-all duration-300"
                        style={{ width: `${totalCount ? (completedCount / totalCount) * 100 : 0}%` }} />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      <CopilotFAB pageContext={{ active_farm: activeFarm, mode, drone_count: config.count, has_plan: hasPlan }} />
    </div>
  );
}

// ── Sub-components ──

function KPICard({ label, value, unit, color }: { label: string; value: string; unit: string; color: string }) {
  return (
    <div className="industrial-card rounded-lg px-4 py-3 flex items-center gap-3">
      <div className="w-2 h-8 rounded-full" style={{ background: `linear-gradient(180deg, ${color}, ${color}44)` }} />
      <div>
        <p className="text-[10px] text-text-muted">{label}</p>
        <p className="text-lg font-mono font-bold" style={{ color }}>
          {value}<span className="text-xs text-text-muted ml-0.5">{unit}</span>
        </p>
      </div>
    </div>
  );
}

function SliderRow({ label, value, min, max, step, unit, onChange }: {
  label: string; value: number; min: number; max: number; step: number; unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex justify-between text-xs text-text-secondary mb-1">
        <span>{label}</span>
        <span className="text-text-primary font-medium">{value}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-blue-500 h-1.5" />
      <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
        <span>{min}{unit}</span><span>{max}{unit}</span>
      </div>
    </div>
  );
}
