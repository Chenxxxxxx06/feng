/**
 * 3D 风场视图 + 无人机调度状态管理
 * zustand store: 2D DroneSchedulerPage 写 → 3D WindFarm3DView 读
 */

import { create } from 'zustand';
import type { Turbine, Drone, NoFlyZone } from '../types';

export interface Drone3DState {
  // ── 数据 ──
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  hasPlan: boolean;
  isRunning: boolean;
  speedMultiplier: number;

  // ── 禁飞区 ──
  noFlyZones: NoFlyZone[];
  showNoFlyZones: boolean;

  // ── 3D 视图 ──
  viewMode: 'overview' | 'detail';
  focusedTurbineId: number | null;
  cruiseAltitude: number;
  cameraMode: 'follow' | 'overview' | 'free';

  // ── Actions ──
  setTurbines: (t: Turbine[]) => void;
  setDrones: (d: Drone[]) => void;
  setActiveFarm: (f: string | null) => void;
  setHasPlan: (v: boolean) => void;
  setIsRunning: (v: boolean) => void;
  setSpeedMultiplier: (v: number) => void;
  setViewMode: (m: 'overview' | 'detail') => void;
  focusTurbine: (id: number | null) => void;
  setNoFlyZones: (zones: NoFlyZone[]) => void;
  addNoFlyZone: (zone: NoFlyZone) => void;
  removeNoFlyZone: (index: number) => void;
  toggleNoFlyZones: () => void;
  setCruiseAltitude: (alt: number) => void;
  setCameraMode: (mode: 'follow' | 'overview' | 'free') => void;
}

export const useDrone3DStore = create<Drone3DState>((set) => ({
  turbines: [],
  drones: [],
  activeFarm: null,
  hasPlan: false,
  isRunning: false,
  speedMultiplier: 1,

  noFlyZones: [],
  showNoFlyZones: true,

  viewMode: 'overview',
  focusedTurbineId: null,
  cruiseAltitude: 50,
  cameraMode: 'overview',

  setTurbines: (turbines) => set({ turbines }),
  setDrones: (drones) => set({ drones }),
  setActiveFarm: (activeFarm) => set({ activeFarm }),
  setHasPlan: (hasPlan) => set({ hasPlan }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setSpeedMultiplier: (speedMultiplier) => set({ speedMultiplier }),
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
}));
