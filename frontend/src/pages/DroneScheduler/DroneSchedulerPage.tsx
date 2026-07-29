import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import api from '../../services/api';
import DroneMap from '../../components/Map/DroneMap';
import ErrorBoundary from '../../components/Common/ErrorBoundary';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';
import { solveVrp } from '../../utils/dronePathPlanner';
import { buildFleet, createDefaultConfig, tickSimulation } from '../../utils/droneSimulator';
import { useDrone3DStore } from '../../services/drone3dStore';
import {
  PART_TO_ANGLE,
  buildSimulatedFrame,
  captureImage,
  checkImageQuality,
  createIncidentFromMission,
  createMission,
  describeDroneError,
  detectDefects,
  fetchMissingAngles,
  isOfflineError,
  linkEvidence,
  updateMissionStatus,
} from '../../services/droneService';
import type { MissingAnglesResult, MissionIncidentResult } from '../../services/droneService';
import type { Drone, DroneFleetConfig, InspectionTargetPart, InspectionWaypoint, Turbine } from '../../types';
import { Skeleton } from '../../components/Common/Skeleton';

const WindFarm3DView = lazy(() => import('../../components/Map/three/WindFarm3DView'));

const PART_LABELS: Record<InspectionTargetPart, string> = {
  blade_tip: '叶尖',
  blade_root: '叶根',
  leading_edge: '叶片前缘',
  trailing_edge: '叶片后缘',
  hub: '轮毂',
  nacelle: '机舱',
};

const METERS_PER_DEG_LAT = 111_320;
const DEFAULT_SHOOT_DISTANCE = 18;
const TAKEOFF_ALTITUDE = 8;
const TAKEOFF_DISTANCE_M = 360;
const TAKEOFF_SIDE_SPACING_M = 120;

function metersPerDegLng(lat: number): number {
  return 111_320 * Math.cos((lat * Math.PI) / 180);
}

function offsetLatLng(lat: number, lng: number, northM: number, eastM: number) {
  return {
    lat: lat + northM / METERS_PER_DEG_LAT,
    lng: lng + eastM / metersPerDegLng(lat),
  };
}

function partTarget(part: InspectionTargetPart) {
  const targets: Record<InspectionTargetPart, { east: number; north: number; alt: number }> = {
    blade_tip: { east: 2, north: 0, alt: 115 },
    blade_root: { east: 2, north: 0, alt: 86 },
    leading_edge: { east: 2, north: -8, alt: 104 },
    trailing_edge: { east: 2, north: 8, alt: 104 },
    hub: { east: 2, north: 0, alt: 82 },
    nacelle: { east: -3, north: 0, alt: 84 },
  };
  return targets[part];
}

function inspectionAltitude(part: InspectionTargetPart): number {
  const target = partTarget(part);
  const margins: Record<InspectionTargetPart, number> = {
    blade_tip: 10,
    blade_root: 8,
    leading_edge: 9,
    trailing_edge: 9,
    hub: 8,
    nacelle: 8,
  };
  return target.alt + margins[part];
}

function offsetFromPoint(point: { lat: number; lng: number }, northM: number, eastM: number) {
  return {
    lat: point.lat + northM / METERS_PER_DEG_LAT,
    lng: point.lng + eastM / metersPerDegLng(point.lat),
  };
}

function buildRouteWithTakeoff(drone: Drone, part: InspectionTargetPart): Drone {
  const inspectionPath = drone.path.filter((p) => p.kind !== 'takeoff' && p.kind !== 'climb' && p.kind !== 'return');
  if (inspectionPath.length === 0) return drone;

  const first = inspectionPath[0];
  const next = inspectionPath[1] ?? first;
  const north = (next.lat - first.lat) * METERS_PER_DEG_LAT;
  const east = (next.lng - first.lng) * metersPerDegLng(first.lat);
  const length = Math.max(1, Math.hypot(north, east));
  const forwardNorth = north / length;
  const forwardEast = east / length;
  const side = drone.id % 2 === 0 ? 1 : -1;
  const base = offsetFromPoint(
    first,
    -forwardNorth * TAKEOFF_DISTANCE_M + -forwardEast * side * TAKEOFF_SIDE_SPACING_M,
    -forwardEast * TAKEOFF_DISTANCE_M + forwardNorth * side * TAKEOFF_SIDE_SPACING_M,
  );
  const cruiseAlt = inspectionAltitude(part);
  const climb = offsetFromPoint(
    first,
    -forwardNorth * 180 + -forwardEast * side * 60,
    -forwardEast * 180 + forwardNorth * side * 60,
  );
  const enrichedPath = [
    { ...base, alt: TAKEOFF_ALTITUDE, kind: 'takeoff' as const },
    { ...climb, alt: cruiseAlt, kind: 'climb' as const },
    ...inspectionPath.map((p) => ({ ...p, alt: cruiseAlt, kind: 'inspect' as const })),
    { ...climb, alt: cruiseAlt, kind: 'return' as const },
    { ...base, alt: TAKEOFF_ALTITUDE, kind: 'return' as const },
  ];

  return {
    ...drone,
    path: enrichedPath,
    currentPosition: { lat: base.lat, lng: base.lng },
    progress: 0,
    _altitude: cruiseAlt,
  };
}

function buildInspectionWaypoints(
  turbine: Turbine | undefined,
  part: InspectionTargetPart,
): InspectionWaypoint[] {
  if (!turbine) return [];

  const target = partTarget(part);
  const label = PART_LABELS[part];
  const orbitAngles = part === 'hub' || part === 'nacelle' ? [-32, 0, 32] : [-28, 0, 28, 56];

  return orbitAngles.map((deg, index) => {
    const rad = (deg * Math.PI) / 180;
    const droneEast = target.east - Math.cos(rad) * DEFAULT_SHOOT_DISTANCE;
    const droneNorth = target.north + Math.sin(rad) * DEFAULT_SHOOT_DISTANCE;
    const droneAlt = target.alt + (index % 2 === 0 ? 4 : -3);
    const pos = offsetLatLng(turbine.lat, turbine.lng, droneNorth, droneEast);
    const yaw = (Math.atan2(target.east - droneEast, target.north - droneNorth) * 180) / Math.PI;
    const horizontal = Math.max(1, Math.hypot(target.east - droneEast, target.north - droneNorth));
    const pitch = (Math.atan2(target.alt - droneAlt, horizontal) * 180) / Math.PI;

    return {
      id: `${turbine.id}-${part}-${index + 1}`,
      turbineId: turbine.id,
      position: [pos.lat, pos.lng, droneAlt],
      targetOffset: [target.east - droneEast, target.alt - droneAlt, target.north - droneNorth],
      targetPart: `${turbine.name}-${label}`,
      cameraYaw: Math.round(yaw),
      cameraPitch: Math.round(pitch),
      shootDistance: DEFAULT_SHOOT_DISTANCE,
      action: '拍照',
    };
  });
}

type ShotStage = 'capturing' | 'quality' | 'detect' | 'evidence' | 'done' | 'retake' | 'error';

/** 单次拍摄的后端回执 —— 字段全部来自 /api/drone 响应，前端不做本地推断 */
interface ShotRecord {
  seq: number;
  angle: string;
  degraded: boolean;
  stage: ShotStage;
  imageId: number | null;
  imagePath: string | null;
  qualityPassed: boolean | null;
  blurScore: number | null;
  issues: string[];
  retakeReason: string | null;
  diagnosisType: string | null;
  confidence: number | null;
  algorithmMode: string | null;
  modelVersion: string | null;
  defectCount: number | null;
  evidenceId: number | null;
  error: string | null;
}

interface ActiveMission {
  missionId: string;
  turbineId: number;
  turbineName: string;
  part: InspectionTargetPart;
  waypoints: InspectionWaypoint[];
  finished: boolean;
}

const ALGORITHM_MODE_LABELS: Record<string, string> = {
  real_inference: '真实模型推理',
  demo_fixture: '演示样例数据(非真实检测)',
};

export default function DroneSchedulerPage() {
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [activeFarm, setActiveFarm] = useState<string | null>(null);
  const [config, setConfig] = useState<DroneFleetConfig>(createDefaultConfig());
  const [inspectionPart, setInspectionPart] = useState<InspectionTargetPart>('blade_tip');
  const [selectedInspectionTurbineId, setSelectedInspectionTurbineId] = useState<number | null>(null);
  const [drones, setDrones] = useState<Drone[]>([]);
  const [selectedDroneId, setSelectedDroneId] = useState<number | null>(null);
  const [hasPlan, setHasPlan] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const [elapsedTime, setElapsedTime] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);

  // ── 后端巡检任务（真实落库）──
  const [missionId, setMissionId] = useState<string | null>(null);
  const [missionStatus, setMissionStatus] = useState<'idle' | 'planned' | 'in_flight' | 'completed' | 'aborted'>('idle');
  const [backendMode, setBackendMode] = useState<'idle' | 'online' | 'offline'>('idle');
  const [backendNote, setBackendNote] = useState('');
  const [shots, setShots] = useState<ShotRecord[]>([]);
  const [missingAngles, setMissingAngles] = useState<MissingAnglesResult | null>(null);
  const [incident, setIncident] = useState<MissionIncidentResult | null>(null);
  const [incidentBusy, setIncidentBusy] = useState(false);
  const [injectDegraded, setInjectDegraded] = useState(false);
  /** 落库流水线是否在跑 —— 与本地 3D 动画解耦，动画先结束也要把剩余航点拍完 */
  const [capturing, setCapturing] = useState(false);

  const animRef = useRef<number | null>(null);
  const lastTickRef = useRef(0);
  const missionRef = useRef<ActiveMission | null>(null);
  const shotCursorRef = useRef(0);
  const degradedRef = useRef(false);
  const missionStartingRef = useRef(false);

  const storeSetTurbines = useDrone3DStore((s) => s.setTurbines);
  const storeSetDrones = useDrone3DStore((s) => s.setDrones);
  const storeSetInspectionWaypoints = useDrone3DStore((s) => s.setInspectionWaypoints);
  const storeSetSelectedInspectionTurbine = useDrone3DStore((s) => s.setSelectedInspectionTurbine);
  const storeSetInspectionTargetPart = useDrone3DStore((s) => s.setInspectionTargetPart);
  const storeSetSelectedDroneId = useDrone3DStore((s) => s.setSelectedDroneId);

  const farms = useMemo(() => {
    const values = new Set<string>();
    turbines.forEach((t) => { if (t.region) values.add(t.region); });
    return Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }, [turbines]);

  const farmTurbines = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm) : [],
    [activeFarm, turbines],
  );

  const selectedInspectionTurbine = useMemo(
    () => turbines.find((t) => t.id === selectedInspectionTurbineId),
    [selectedInspectionTurbineId, turbines],
  );

  const inspectionWaypoints = useMemo(
    () => buildInspectionWaypoints(selectedInspectionTurbine, inspectionPart),
    [inspectionPart, selectedInspectionTurbine],
  );

  useEffect(() => {
    api.get<{ turbines: Turbine[] }>('/turbines/')
      .then(({ data }) => {
        setTurbines(data.turbines);
        storeSetTurbines(data.turbines);
      })
      .catch(() => setMessage('风机数据加载失败'))
      .finally(() => setLoading(false));
  }, [storeSetTurbines]);

  useEffect(() => {
    const store = useDrone3DStore.getState();
    store.setActiveFarm(activeFarm);
    store.setCruiseAltitude(inspectionAltitude(inspectionPart));

    if (!activeFarm) {
      setHasPlan(false);
      setDrones([]);
      setSelectedDroneId(null);
      setSelectedInspectionTurbineId(null);
      setIsRunning(false);
      store.setHasPlan(false);
      store.setInspectionWaypoints([]);
      store.setSelectedInspectionTurbine(null);
      store.setSelectedDroneId(null);
      return;
    }

    const firstId = farmTurbines[0]?.id ?? null;
    if (!farmTurbines.some((t) => t.id === selectedInspectionTurbineId)) {
      setSelectedInspectionTurbineId(firstId);
      store.setSelectedInspectionTurbine(firstId);
    }
  }, [activeFarm, farmTurbines, selectedInspectionTurbineId]);

  useEffect(() => {
    storeSetDrones(drones);
  }, [drones, storeSetDrones]);

  useEffect(() => {
    storeSetSelectedDroneId(selectedDroneId);
  }, [selectedDroneId, storeSetSelectedDroneId]);

  useEffect(() => {
    storeSetInspectionTargetPart(inspectionPart);
    storeSetSelectedInspectionTurbine(selectedInspectionTurbineId);
    storeSetInspectionWaypoints(hasPlan ? inspectionWaypoints : []);
  }, [
    hasPlan,
    inspectionPart,
    inspectionWaypoints,
    selectedInspectionTurbineId,
    storeSetInspectionTargetPart,
    storeSetInspectionWaypoints,
    storeSetSelectedInspectionTurbine,
  ]);

  useEffect(() => {
    degradedRef.current = injectDegraded;
  }, [injectDegraded]);

  // ── 后端巡检任务：创建 → 逐航点拍摄落库 → 质量门 → 缺陷检测 → 证据 → 结束 ──

  const updateShot = useCallback((seq: number, patch: Partial<ShotRecord>) => {
    setShots((prev) => prev.map((s) => (s.seq === seq ? { ...s, ...patch } : s)));
  }, []);

  const goOffline = useCallback((reason: string) => {
    setBackendMode('offline');
    setBackendNote(`后端不可用，已降级为离线演示（3D 仿真继续，不产生落库记录）：${reason}`);
  }, []);

  const resetMissionState = useCallback(() => {
    const active = missionRef.current;
    if (active && !active.finished) {
      // 尽力而为地把未完成任务置为 aborted，失败不影响本地演示
      updateMissionStatus(active.missionId, 'aborted').catch(() => undefined);
    }
    missionRef.current = null;
    shotCursorRef.current = 0;
    missionStartingRef.current = false;
    setCapturing(false);
    setMissionId(null);
    setMissionStatus('idle');
    setShots([]);
    setMissingAngles(null);
    setIncident(null);
    setBackendMode('idle');
    setBackendNote('');
    useDrone3DStore.getState().resetMissionTelemetry();
  }, []);

  // 切换巡检风机/部位意味着换一个任务对象，旧任务在后端置为 aborted
  useEffect(() => {
    if (missionRef.current) resetMissionState();
  }, [inspectionPart, resetMissionState, selectedInspectionTurbineId]);

  const startMission = useCallback(async () => {
    if (missionRef.current || missionStartingRef.current) return;
    const turbine = selectedInspectionTurbine;
    if (!turbine || inspectionWaypoints.length === 0) {
      setBackendNote('未选择巡检风机，本次仅本地演示');
      return;
    }
    missionStartingRef.current = true;
    const part = inspectionPart;
    const angle = PART_TO_ANGLE[part] ?? part;
    const waypoints = inspectionWaypoints;
    // 该风机由本地 VRP 分配给哪架无人机 —— 一并写入任务档案
    const assignedDrone = useDrone3DStore
      .getState()
      .drones.find((d) => d.assignedTurbines.includes(turbine.id));

    try {
      const created = await createMission({
        turbine_id: turbine.id,
        component: part,
        // 航点来自本地 VRP/环绕规划算法（buildInspectionWaypoints），原样上报后端存档
        waypoints: waypoints.map((w, index) => ({
          lat: w.position[0],
          lng: w.position[1],
          alt: w.position[2],
          angle,
          part,
          seq: index + 1,
        })),
        drone_id: assignedDrone?.name,
      });
      missionRef.current = {
        missionId: created.mission_id,
        turbineId: turbine.id,
        turbineName: created.turbine_name || turbine.name,
        part,
        waypoints,
        finished: false,
      };
      shotCursorRef.current = 0;
      setMissionId(created.mission_id);
      setMissionStatus('planned');
      setBackendMode('online');
      setBackendNote(`任务 ${created.mission_id} 已创建（${waypoints.length} 个航点）`);
      try {
        await updateMissionStatus(created.mission_id, 'in_flight');
        setMissionStatus('in_flight');
      } catch (err) {
        setBackendNote(`任务状态更新失败：${describeDroneError(err)}`);
      }
    } catch (err) {
      const reason = describeDroneError(err);
      if (isOfflineError(err)) goOffline(reason);
      else {
        setBackendMode('offline');
        setBackendNote(`创建巡检任务失败，本次仅本地演示：${reason}`);
      }
    } finally {
      missionStartingRef.current = false;
    }
  }, [goOffline, inspectionPart, inspectionWaypoints, selectedInspectionTurbine]);

  const runCaptureStep = useCallback(async (index: number) => {
    const mission = missionRef.current;
    const waypoint = mission?.waypoints[index];
    if (!mission || !waypoint) return;

    const seq = index + 1;
    const angle = PART_TO_ANGLE[mission.part] ?? mission.part;
    const degraded = degradedRef.current;

    setShots((prev) => [
      ...prev,
      {
        seq,
        angle,
        degraded,
        stage: 'capturing',
        imageId: null,
        imagePath: null,
        qualityPassed: null,
        blurScore: null,
        issues: [],
        retakeReason: null,
        diagnosisType: null,
        confidence: null,
        algorithmMode: null,
        modelVersion: null,
        defectCount: null,
        evidenceId: null,
        error: null,
      },
    ]);

    try {
      const frame = await buildSimulatedFrame({
        missionId: mission.missionId,
        turbineName: mission.turbineName,
        partLabel: PART_LABELS[mission.part],
        angle,
        seq,
        total: mission.waypoints.length,
        altitudeM: waypoint.position[2],
        yawDeg: waypoint.cameraYaw,
        pitchDeg: waypoint.cameraPitch,
        shootDistanceM: waypoint.shootDistance,
        degraded,
      });

      const captured = await captureImage(mission.missionId, frame, {
        turbine_id: mission.turbineId,
        component: mission.part,
        angle,
        waypoint_index: index,
        gps_lat: waypoint.position[0],
        gps_lng: waypoint.position[1],
        altitude_m: waypoint.position[2],
        shoot_distance_m: waypoint.shootDistance,
        data_source: 'sim_3d_render',
        data_license: 'internal_demo_only',
      });
      updateShot(seq, { imageId: captured.id, imagePath: captured.image_path, stage: 'quality' });

      const quality = await checkImageQuality(captured.id);
      updateShot(seq, {
        qualityPassed: quality.passed,
        blurScore: quality.blur_score,
        issues: quality.issues || [],
        retakeReason: quality.retake_reason,
        stage: quality.passed ? 'detect' : 'retake',
      });
      if (!quality.passed) return;

      const detection = await detectDefects(captured.id);
      updateShot(seq, {
        diagnosisType: detection.diagnosis_type,
        confidence: detection.diagnosis_confidence,
        algorithmMode: detection.algorithm_mode,
        modelVersion: detection.model_version,
        defectCount: detection.defects_detected?.length ?? 0,
        stage: 'evidence',
      });

      const evidence = await linkEvidence(captured.id);
      updateShot(seq, { evidenceId: evidence.evidence_id, stage: 'done' });
    } catch (err) {
      const reason = describeDroneError(err);
      updateShot(seq, { stage: 'error', error: reason });
      if (isOfflineError(err)) goOffline(reason);
    }
  }, [goOffline, updateShot]);

  const finishMission = useCallback(async () => {
    const mission = missionRef.current;
    if (!mission || mission.finished) return;
    mission.finished = true;
    setCapturing(false);
    try {
      await updateMissionStatus(mission.missionId, 'completed');
      setMissionStatus('completed');
      const angles = await fetchMissingAngles(mission.missionId);
      setMissingAngles(angles);
      setBackendNote(`任务 ${mission.missionId} 已完成并落库`);
    } catch (err) {
      const reason = describeDroneError(err);
      setBackendNote(`任务收尾失败：${reason}`);
      if (isOfflineError(err)) goOffline(reason);
    }
  }, [goOffline]);

  const handleCreateIncident = useCallback(async () => {
    const mission = missionRef.current;
    if (!mission) return;
    setIncidentBusy(true);
    try {
      const result = await createIncidentFromMission(mission.missionId);
      setIncident(result);
      setBackendNote(`事件 ${result.incident_id} 已${result.already_exists ? '存在' : '创建'}`);
    } catch (err) {
      setBackendNote(`创建事件失败：${describeDroneError(err)}`);
    } finally {
      setIncidentBusy(false);
    }
  }, []);

  const planPath = useCallback((farm: string, cfg: DroneFleetConfig) => {
    const scoped = turbines.filter((t) => t.region === farm);
    if (!scoped.length) {
      setMessage('该风场无风机数据');
      return;
    }

    const points = scoped.map((t) => ({ lat: t.lat, lng: t.lng, id: t.id, name: t.name }));
    const result = solveVrp(points, cfg.count);
    const fleet = buildFleet(result, cfg, farm).map((d) => buildRouteWithTakeoff(d, inspectionPart));
    const distance = result.totalDistance;
    const nextSelectedDroneId = fleet[0]?.id ?? null;

    resetMissionState();
    setDrones(fleet);
    setSelectedDroneId(nextSelectedDroneId);
    setHasPlan(true);
    setIsRunning(false);
    setCompletedCount(0);
    setTotalCount(points.length);
    setElapsedTime(0);
    setMessage(`${cfg.count}机分区 · ${distance.toLocaleString()}m · ${points.length}台风机`);
    useDrone3DStore.getState().setHasPlan(true);
    useDrone3DStore.getState().setSelectedDroneId(nextSelectedDroneId);
  }, [inspectionPart, resetMissionState, turbines]);

  useEffect(() => {
    if (activeFarm && turbines.length > 0) {
      planPath(activeFarm, config);
    }
  }, [activeFarm, turbines.length]);

  const handleFarmSelect = (farm: string | null) => {
    setActiveFarm(farm);
    setMessage('');
  };

  const handleTurbineClick = (turbine: Turbine) => {
    setSelectedInspectionTurbineId(turbine.id);
    storeSetSelectedInspectionTurbine(turbine.id);
  };

  useEffect(() => {
    if (!isRunning || drones.length === 0) return undefined;
    lastTickRef.current = 0;

    const tick = () => {
      const now = performance.now();
      const dt = lastTickRef.current ? (now - lastTickRef.current) / 1000 : 0.05;
      lastTickRef.current = now;
      const clampedDt = Math.min(dt, 0.2);

      setDrones((prev) => {
        const { fleet, allComplete, completedThisTick } = tickSimulation(prev, clampedDt, speedMultiplier);
        if (completedThisTick > 0) setCompletedCount((count) => count + completedThisTick);
        if (allComplete) {
          setIsRunning(false);
          useDrone3DStore.getState().setIsRunning(false);
          setMessage('全部风机已拍摄完成');
        }
        return fleet;
      });
      setElapsedTime((time) => time + clampedDt * speedMultiplier);
      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [drones.length, isRunning, speedMultiplier]);

  // 飞行过程中按航点节奏真实落库：capture → quality-check → detect → link-evidence
  useEffect(() => {
    if (!capturing || !missionId || backendMode !== 'online') return undefined;
    let cancelled = false;
    let timer = 0;

    const step = async () => {
      if (cancelled) return;
      const mission = missionRef.current;
      if (!mission) return;
      const index = shotCursorRef.current;
      if (index >= mission.waypoints.length) {
        void finishMission();
        return;
      }
      shotCursorRef.current = index + 1;
      await runCaptureStep(index);
      if (cancelled) return;
      timer = window.setTimeout(step, Math.max(500, 2400 / speedMultiplier));
    };

    timer = window.setTimeout(step, 600);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [backendMode, capturing, finishMission, missionId, runCaptureStep, speedMultiplier]);

  const loggedShots = shots.filter((s) => s.imageId !== null).length;
  const qualityPassedShots = shots.filter((s) => s.qualityPassed === true).length;
  const retakeShots = shots.filter((s) => s.qualityPassed === false).length;
  const defectShots = shots.filter((s) => s.diagnosisType && s.diagnosisType !== 'no_damage').length;
  const evidenceShots = shots.filter((s) => s.evidenceId !== null).length;
  const missionWaypointCount = missionRef.current?.waypoints.length ?? inspectionWaypoints.length;

  useEffect(() => {
    useDrone3DStore.getState().setMissionTelemetry({
      missionId,
      missionStatus,
      online: backendMode === 'online',
      shotCount: loggedShots,
      passedCount: qualityPassedShots,
      defectCount: defectShots,
    });
  }, [backendMode, defectShots, loggedShots, missionId, missionStatus, qualityPassedShots]);

  const formatTime = (seconds: number) => {
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    return `${min}:${String(sec).padStart(2, '0')}`;
  };

  const setRunState = (value: boolean) => {
    setIsRunning(value);
    useDrone3DStore.getState().setIsRunning(value);
  };

  const handleStart = () => {
    setRunState(true);
    setCapturing(true);
    if (!missionRef.current) void startMission();
  };

  const handlePause = () => {
    setRunState(false);
    setCapturing(false);
  };

  const replan = () => {
    if (activeFarm) planPath(activeFarm, config);
  };

  const resetSimulation = () => {
    replan();
    setRunState(false);
  };

  const activeDroneCount = drones.filter((d) => d.status === 'flying').length;
  const assignedTotal = drones.reduce((sum, d) => sum + d.assignedTurbines.length, 0);
  const averageBattery = drones.length
    ? Math.round(drones.reduce((sum, d) => sum + d.battery, 0) / drones.length)
    : 0;
  if (loading) {
    return (
      <div className="flex h-full flex-col overflow-hidden p-4" role="status" aria-label="无人机调度数据加载中" style={{ background: 'radial-gradient(ellipse at 50% 30%, #0f1a2e 0%, #080c12 70%)' }}>
        <div className="flex items-center gap-4 border-b border-border-subtle pb-3">
          <Skeleton width={220} height={16} radius={5} />
          <Skeleton className="skeleton-pill" width={92} />
        </div>
        <div className="mt-4 grid flex-1 gap-4" style={{ gridTemplateColumns: 'minmax(0, 1fr) 320px' }}>
          <Skeleton className="h-full w-full" radius={16} />
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} height={72} radius={12} style={{ opacity: Math.max(0.4, 1 - i * 0.13) }} />
            ))}
          </div>
        </div>
        <span className="sr-only">正在加载风机与无人机数据</span>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden" style={{ background: 'radial-gradient(ellipse at 50% 30%, #0f1a2e 0%, #080c12 70%)' }}>
      <div className="flex-shrink-0 border-b border-border-subtle px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h2 className="text-base font-bold tracking-wide">
              <span className="gradient-text">无人机调度 · 数据获取</span>
            </h2>
            <span className="rounded-full border border-border-subtle bg-bg-card px-2.5 py-0.5 text-[10px] text-text-muted">
              共 {turbines.length} 台风机
            </span>
            <div className="relative">
              <select
                value={activeFarm || ''}
                onChange={(event) => handleFarmSelect(event.target.value || null)}
                className="appearance-none rounded-lg border border-border-default bg-bg-card px-3 py-1.5 pr-8 text-xs text-text-primary outline-none transition-colors hover:border-accent-blue/40"
              >
                <option value="">📍 风场总览</option>
                {farms.map((farm) => (
                  <option key={farm} value={farm}>📍 {farm}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-accent-blue">▾</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {message && <span className="text-[10px] text-text-muted">{message}</span>}
            <span className={`flex items-center gap-1.5 text-[11px] ${hasPlan ? 'text-accent-blue' : 'text-text-muted'}`}>
              <span className={`h-2 w-2 rounded-full ${hasPlan ? 'status-dot-live' : ''}`} style={{ background: hasPlan ? '#388bfd' : '#54657e' }} />
              {hasPlan ? '路径已规划' : activeFarm ? '等待规划' : '总览模式'}
            </span>
          </div>
        </div>
      </div>

      <div className="flex-shrink-0 px-6 py-3">
        <div className="grid grid-cols-5 gap-3">
          <KPICard label="风机总数" value={String(turbines.length)} unit="台" color="#388bfd" />
          <KPICard label="当前风场" value={activeFarm ? String(farmTurbines.length) : '--'} unit="台" color="#39d2c0" />
          <KPICard label="无人机" value={hasPlan ? String(drones.length) : '--'} unit="架" color="#a371f7" />
          <KPICard label="仿真覆盖风机" value={hasPlan ? `${completedCount}/${totalCount}` : '--'} unit="" color="#d29922" />
          <KPICard
            label="后端落库照片"
            value={missionId ? `${loggedShots}/${missionWaypointCount}` : '--'}
            unit=""
            color="#3fb950"
          />
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_1fr_300px] gap-4 px-6 pb-6">
        <div className="relative overflow-hidden rounded-xl border border-border-subtle" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <DroneMap
            turbines={turbines}
            drones={drones}
            activeFarm={activeFarm}
            onFarmSelect={handleFarmSelect}
            onTurbineClick={handleTurbineClick}
            showPaths={hasPlan}
          />
        </div>

        <div className="relative overflow-hidden rounded-xl border border-border-subtle" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <ErrorBoundary fallback={
            <div className="flex h-full items-center justify-center bg-[#071A35] text-text-muted">
              3D 视图加载失败
            </div>
          }>
            <Suspense fallback={
              <div className="flex h-full items-center justify-center bg-[#071A35] text-text-muted">
                正在加载 3D 引擎…
              </div>
            }>
              <WindFarm3DView />
            </Suspense>
          </ErrorBoundary>
        </div>

        <aside className="min-h-0 overflow-y-auto rounded-xl border border-border-subtle bg-bg-card/80 p-4">
          <div className="mb-4">
            <h3 className="text-sm font-bold">巡检控制</h3>
            <p className="text-[10px] text-text-muted">
              {activeFarm ? `${activeFarm} · ${farmTurbines.length}台风机` : '先在地图或下拉框选择风场'}
            </p>
          </div>

          <ControlSection title="路线规划">
            <div className="mb-3 rounded-md border border-accent-blue/20 bg-accent-blue/10 px-3 py-2 text-[10px] text-accent-blue">
              当前使用多机分区巡检：按风机位置自动分组，并为每组生成最短访问顺序。
            </div>
            <SliderRow
              label="无人机数量"
              value={config.count}
              min={1}
              max={6}
              step={1}
              unit="架"
              onChange={(value) => setConfig({ ...config, count: value })}
            />
            <button
              type="button"
              disabled={!activeFarm}
              onClick={replan}
              className="mt-3 w-full rounded-md bg-accent-blue px-3 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              规划路线
            </button>
          </ControlSection>

          <ControlSection title="拍摄目标">
            <label className="mb-1 block text-[10px] text-text-muted">当前风机</label>
            <select
              value={selectedInspectionTurbineId ?? ''}
              disabled={!activeFarm}
              onChange={(event) => setSelectedInspectionTurbineId(Number(event.target.value))}
              className="mb-3 w-full rounded-md border border-accent-blue/25 bg-[#0f172a] px-2 py-1.5 text-xs text-[#dbeafe] outline-none disabled:opacity-50"
              style={{ colorScheme: 'dark' }}
            >
              {farmTurbines.map((t) => (
                <option key={t.id} value={t.id} className="bg-[#0f172a] text-[#dbeafe]">{t.name}</option>
              ))}
            </select>
            <div className="grid grid-cols-2 gap-1.5">
              {(Object.keys(PART_LABELS) as InspectionTargetPart[]).map((part) => (
                <button
                  key={part}
                  type="button"
                  disabled={!activeFarm}
                  onClick={() => setInspectionPart(part)}
                  className={`rounded-md border px-2 py-1.5 text-[10px] transition-colors disabled:opacity-50 ${
                    inspectionPart === part ? 'border-accent-blue/60 bg-accent-blue/15 text-[#dbeafe] shadow-[0_0_12px_rgba(56,139,253,0.18)]' : 'border-border-default bg-[#0b1220]/70 text-text-secondary hover:border-accent-blue/40 hover:bg-accent-blue/10'
                  }`}
                >
                  {PART_LABELS[part]}
                </button>
              ))}
            </div>
          </ControlSection>

          <ControlSection title="任务执行">
            <div className="mb-3 rounded-md border border-border-subtle bg-bg-panel/60 p-2 text-[10px] text-text-muted">
              <div className="flex justify-between">
                <span>飞行时间</span>
                <span>{isRunning ? formatTime(elapsedTime) : '--'}</span>
              </div>
              <div className="mt-1 flex justify-between">
                <span>仿真覆盖风机</span>
                <span>{hasPlan ? `${completedCount}/${totalCount}` : '--'}</span>
              </div>
              <div className="mt-1 flex justify-between">
                <span>后端落库照片</span>
                <span className={missionId ? 'text-accent-green' : ''}>
                  {missionId ? `${loggedShots}/${missionWaypointCount}` : '--'}
                </span>
              </div>
            </div>
            <div className="mb-2 grid grid-cols-2 gap-2">
              {!isRunning ? (
                <button
                  type="button"
                  disabled={!hasPlan}
                  onClick={handleStart}
                  className="rounded-md bg-accent-blue px-3 py-2 text-xs text-white disabled:cursor-not-allowed disabled:opacity-40"
                >
                  执行
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handlePause}
                  className="rounded-md bg-accent-yellow px-3 py-2 text-xs text-bg-base"
                >
                  暂停
                </button>
              )}
              <button
                type="button"
                disabled={!hasPlan}
                onClick={resetSimulation}
                className="rounded-md border border-border-default px-3 py-2 text-xs text-text-secondary disabled:cursor-not-allowed disabled:opacity-40"
              >
                重置
              </button>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {[1, 2, 4, 8].map((speed) => (
                <button
                  key={speed}
                  type="button"
                  onClick={() => {
                    setSpeedMultiplier(speed);
                    useDrone3DStore.getState().setSpeedMultiplier(speed);
                  }}
                  className={`rounded border px-1.5 py-1 text-[10px] ${speedMultiplier === speed ? 'border-accent-blue/50 bg-accent-blue/10 text-accent-blue' : 'border-border-default text-text-muted'}`}
                >
                  {speed}×
                </button>
              ))}
            </div>
          </ControlSection>

          <ControlSection title="巡检落库 · 后端真实记录">
            <div className="mb-2 flex items-center justify-between">
              <span className={`rounded px-1.5 py-0.5 text-[10px] ${
                backendMode === 'online'
                  ? 'bg-accent-green/15 text-accent-green'
                  : backendMode === 'offline'
                    ? 'bg-accent-yellow/15 text-accent-yellow'
                    : 'bg-bg-panel/60 text-text-muted'
              }`}>
                {backendMode === 'online' ? '● 已连后端' : backendMode === 'offline' ? '● 离线演示' : '○ 未开始'}
              </span>
              <span className="font-mono text-[10px] text-text-muted">
                {missionId ?? '未创建任务'}
              </span>
            </div>

            {backendNote && (
              <p className="mb-2 break-all rounded border border-border-subtle bg-bg-panel/60 px-2 py-1 text-[10px] text-text-secondary">
                {backendNote}
              </p>
            )}

            {missionId && (
              <div className="mb-2 grid grid-cols-2 gap-1 text-[10px] text-text-muted">
                <span>任务状态 <b className="text-text-primary">{missionStatus}</b></span>
                <span>落库照片 <b className="text-text-primary">{loggedShots}/{missionWaypointCount}</b></span>
                <span>质量通过 <b className="text-accent-green">{qualityPassedShots}</b></span>
                <span>需补拍 <b className={retakeShots ? 'text-accent-yellow' : 'text-text-primary'}>{retakeShots}</b></span>
                <span>检出缺陷 <b className={defectShots ? 'text-accent-red' : 'text-text-primary'}>{defectShots}</b></span>
                <span>证据节点 <b className="text-text-primary">{evidenceShots}</b></span>
              </div>
            )}

            {shots.length > 0 && (
              <div className="mb-2 max-h-48 space-y-1 overflow-y-auto">
                {shots.map((shot) => (
                  <ShotRow key={shot.seq} shot={shot} />
                ))}
              </div>
            )}

            {missingAngles && (
              <div className="mb-2 rounded border border-border-subtle bg-bg-panel/60 px-2 py-1.5 text-[10px] text-text-muted">
                <div className={missingAngles.evidence_complete ? 'text-accent-green' : 'text-accent-yellow'}>
                  证据完整性：{missingAngles.evidence_complete ? '完整' : '不完整'}
                </div>
                <div className="mt-0.5">已采集角度：{missingAngles.captured_angles.join('、') || '无'}</div>
                <div className="mt-0.5">缺失角度：{missingAngles.missing_angles.join('、') || '无'}</div>
                <div className="mt-0.5">待补拍：{missingAngles.retakes_needed} 张</div>
              </div>
            )}

            <button
              type="button"
              disabled={backendMode !== 'online' || !missionId || evidenceShots === 0 || incidentBusy}
              onClick={handleCreateIncident}
              className="w-full rounded-md border border-accent-red/40 bg-accent-red/10 px-3 py-2 text-xs text-accent-red disabled:cursor-not-allowed disabled:opacity-40"
            >
              {incidentBusy ? '创建中...' : '由本次巡检创建事件'}
            </button>

            {incident && (
              <div className="mt-2 rounded border border-accent-red/25 bg-accent-red/5 px-2 py-1.5 text-[10px] text-text-secondary">
                <div className="font-mono text-accent-red">{incident.incident_id}</div>
                <div className="mt-0.5">
                  关联证据 {incident.evidence_linked ?? 0} 条 · {incident.has_defect ? '发现缺陷' : '未发现缺陷'}
                </div>
                {incident.next_action && <div className="mt-0.5">{incident.next_action}</div>}
              </div>
            )}

            <label className="mt-2 flex items-center gap-2 text-[10px] text-text-muted">
              <input
                type="checkbox"
                checked={injectDegraded}
                onChange={(event) => setInjectDegraded(event.target.checked)}
                className="accent-yellow-500"
              />
              注入低质量帧（验证后端补拍门禁）
            </label>

            <p className="mt-2 text-[9px] leading-relaxed text-text-muted">
              披露：3D 飞行与路径规划为本地仿真，上传帧由 Canvas 渲染并烧录 SIMULATED 标识，
              落库标注 data_source=sim_3d_render；质量门、缺陷检测、证据与事件均由后端
              /api/drone 真实计算并入库，上表为后端原样返回结果。
            </p>
          </ControlSection>

          <ControlSection title="任务概况">
            <div className="grid grid-cols-2 gap-2 text-[10px] text-text-muted">
              <SummaryCell label="线路数" value={hasPlan ? `${drones.length}条` : '--'} />
              <SummaryCell label="执行中" value={hasPlan ? `${activeDroneCount}架` : '--'} />
              <SummaryCell label="任务风机" value={hasPlan ? `${assignedTotal}台` : '--'} />
              <SummaryCell label="平均电量" value={hasPlan ? `${averageBattery}%` : '--'} />
            </div>
          </ControlSection>
        </aside>
      </div>

      <CopilotFAB pageContext={{ active_farm: activeFarm, mode: 'vrp', drone_count: config.count, has_plan: hasPlan }} />
    </div>
  );
}

function ControlSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="industrial-card mb-3 rounded-lg p-3">
      <h4 className="mb-2 text-xs font-medium text-text-secondary">{title}</h4>
      {children}
    </section>
  );
}

/** 单帧后端回执：质量门结果 + 检测结果 + 算法模式，全部按后端原文展示 */
function ShotRow({ shot }: { shot: ShotRecord }) {
  const stageLabels: Record<ShotStage, string> = {
    capturing: '上传中',
    quality: '质量检查中',
    detect: '缺陷检测中',
    evidence: '生成证据中',
    done: '已入库',
    retake: '需补拍',
    error: '失败',
  };
  const tone =
    shot.stage === 'error' ? 'text-accent-red'
      : shot.stage === 'retake' ? 'text-accent-yellow'
        : shot.stage === 'done' ? 'text-accent-green'
          : 'text-text-muted';

  return (
    <div className="rounded border border-border-subtle bg-bg-panel/60 px-2 py-1 text-[10px] text-text-muted">
      <div className="flex items-center justify-between">
        <span className="text-text-secondary">
          #{shot.seq} · {shot.angle}
          {shot.degraded && <span className="ml-1 text-accent-yellow">[低质量帧]</span>}
        </span>
        <span className={tone}>{stageLabels[shot.stage]}</span>
      </div>
      {shot.imageId !== null && (
        <div className="mt-0.5 break-all">
          image_id={shot.imageId}
          {shot.imagePath && ` · ${shot.imagePath}`}
        </div>
      )}
      {shot.qualityPassed !== null && (
        <div className="mt-0.5">
          质量门 {shot.qualityPassed ? '通过' : '未通过'}
          {shot.blurScore !== null && ` · 清晰度 ${shot.blurScore}`}
          {shot.issues.length > 0 && (
            <span className="text-accent-yellow"> · {shot.issues.join('；')}</span>
          )}
        </div>
      )}
      {shot.diagnosisType && (
        <div className="mt-0.5">
          检测 {shot.diagnosisType}
          {shot.confidence !== null && ` · 置信度 ${(shot.confidence * 100).toFixed(1)}%`}
          {shot.defectCount !== null && ` · 缺陷 ${shot.defectCount} 处`}
        </div>
      )}
      {shot.algorithmMode && (
        <div className={`mt-0.5 ${shot.algorithmMode === 'real_inference' ? 'text-accent-green' : 'text-accent-yellow'}`}>
          算法模式：{ALGORITHM_MODE_LABELS[shot.algorithmMode] ?? shot.algorithmMode}
          {shot.modelVersion && ` (${shot.modelVersion})`}
        </div>
      )}
      {shot.evidenceId !== null && <div className="mt-0.5">evidence_id={shot.evidenceId}</div>}
      {shot.error && <div className="mt-0.5 break-all text-accent-red">{shot.error}</div>}
    </div>
  );
}

function KPICard({ label, value, unit, color }: { label: string; value: string; unit: string; color: string }) {
  return (
    <div className="industrial-card flex items-center gap-3 rounded-lg px-4 py-3">
      <div className="h-8 w-2 rounded-full" style={{ background: `linear-gradient(180deg, ${color}, ${color}44)` }} />
      <div>
        <p className="text-[10px] text-text-muted">{label}</p>
        <p className="font-mono text-lg font-bold" style={{ color }}>
          {value}<span className="ml-0.5 text-xs text-text-muted">{unit}</span>
        </p>
      </div>
    </div>
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border-subtle bg-bg-panel/60 px-2 py-2">
      <div>{label}</div>
      <div className="mt-1 text-sm font-semibold text-text-primary">{value}</div>
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  unit,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-text-secondary">
        <span>{label}</span>
        <span className="font-medium text-text-primary">{value}{unit}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1.5 w-full accent-blue-500 disabled:opacity-40"
      />
      <div className="mt-0.5 flex justify-between text-[9px] text-text-muted">
        <span>{min}{unit}</span>
        <span>{max}{unit}</span>
      </div>
    </div>
  );
}
