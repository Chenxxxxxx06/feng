/**
 * 3D 风场视图 + 无人机调度状态管理
 * zustand store: 2D DroneSchedulerPage 写 → 3D WindFarm3DView 读
 */

import { create } from 'zustand';
import type { Turbine, Drone, NoFlyZone, InspectionWaypoint, InspectionTargetPart } from '../types';

/**
 * 后端巡检任务实时状态（/api/drone 落库结果的摘要）。
 * online=false 表示后端不可达，页面处于纯本地离线演示。
 */
export interface MissionTelemetry {
  missionId: string | null;
  missionStatus: 'idle' | 'planned' | 'in_flight' | 'completed' | 'aborted';
  online: boolean;
  shotCount: number;
  passedCount: number;
  defectCount: number;
}

const EMPTY_MISSION: MissionTelemetry = {
  missionId: null,
  missionStatus: 'idle',
  online: false,
  shotCount: 0,
  passedCount: 0,
  defectCount: 0,
};

export interface Drone3DState {
  // ── 数据 ──
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  hasPlan: boolean;
  isRunning: boolean;
  speedMultiplier: number;
  inspectionWaypoints: InspectionWaypoint[];
  selectedInspectionTurbineId: number | null;
  inspectionTargetPart: InspectionTargetPart;

  // ── 后端巡检任务 ──
  mission: MissionTelemetry;

  // ── 禁飞区 ──
  noFlyZones: NoFlyZone[];
  showNoFlyZones: boolean;

  // ── 3D 视图 ──
  viewMode: 'overview' | 'detail';
  focusedTurbineId: number | null;
  cruiseAltitude: number;
  cameraMode: 'overview' | 'follow' | 'fpv';
  selectedDroneId: number | null;

  // ── Actions ──
  setTurbines: (t: Turbine[]) => void;
  setDrones: (d: Drone[]) => void;
  setActiveFarm: (f: string | null) => void;
  setHasPlan: (v: boolean) => void;
  setIsRunning: (v: boolean) => void;
  setSpeedMultiplier: (v: number) => void;
  setInspectionWaypoints: (waypoints: InspectionWaypoint[]) => void;
  setSelectedInspectionTurbine: (id: number | null) => void;
  setInspectionTargetPart: (part: InspectionTargetPart) => void;
  setMissionTelemetry: (patch: Partial<MissionTelemetry>) => void;
  resetMissionTelemetry: () => void;
  setViewMode: (m: 'overview' | 'detail') => void;
  focusTurbine: (id: number | null) => void;
  setNoFlyZones: (zones: NoFlyZone[]) => void;
  addNoFlyZone: (zone: NoFlyZone) => void;
  removeNoFlyZone: (index: number) => void;
  toggleNoFlyZones: () => void;
  setCruiseAltitude: (alt: number) => void;
  setCameraMode: (mode: 'overview' | 'follow' | 'fpv') => void;
  setSelectedDroneId: (id: number | null) => void;
}

export const useDrone3DStore = create<Drone3DState>((set) => ({
  turbines: [],
  drones: [],
  activeFarm: null,
  hasPlan: false,
  isRunning: false,
  speedMultiplier: 1,
  inspectionWaypoints: [],
  selectedInspectionTurbineId: null,
  inspectionTargetPart: 'blade_tip',

  mission: EMPTY_MISSION,

  noFlyZones: [],
  showNoFlyZones: true,

  viewMode: 'overview',
  focusedTurbineId: null,
  cruiseAltitude: 50,
  cameraMode: 'overview',
  selectedDroneId: null,

  setTurbines: (turbines) => set({ turbines }),
  setDrones: (drones) => set({ drones }),
  setActiveFarm: (activeFarm) => set({ activeFarm }),
  setHasPlan: (hasPlan) => set({ hasPlan }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setSpeedMultiplier: (speedMultiplier) => set({ speedMultiplier }),
  setInspectionWaypoints: (inspectionWaypoints) => set({ inspectionWaypoints }),
  setSelectedInspectionTurbine: (selectedInspectionTurbineId) => set({ selectedInspectionTurbineId }),
  setInspectionTargetPart: (inspectionTargetPart) => set({ inspectionTargetPart }),
  setMissionTelemetry: (patch) => set((s) => ({ mission: { ...s.mission, ...patch } })),
  resetMissionTelemetry: () => set({ mission: EMPTY_MISSION }),
  setViewMode: (viewMode) => set({ viewMode }),
  focusTurbine: (id) =>
    set({ focusedTurbineId: id, viewMode: id ? 'detail' : 'overview' }),

  setNoFlyZones: (noFlyZones) => set({ noFlyZones }),
  addNoFlyZone: (zone) => set((s) => ({ noFlyZones: [...s.noFlyZones, zone] })),
  removeNoFlyZone: (index) => set((s) => ({
    noFlyZones: s.noFlyZones.filter((_, i) => i !== index),
  })),
  toggleNoFlyZones: () => set((s) => ({ showNoFlyZones: !s.showNoFlyZones })),
  setCruiseAltitude: (cruiseAltitude) => set({ cruiseAltitude }),
  setCameraMode: (cameraMode) => set({ cameraMode }),
  setSelectedDroneId: (selectedDroneId) => set({ selectedDroneId }),
}));
