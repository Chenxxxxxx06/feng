/**
 * 3D 风场视图状态管理
 * 共享 zustand store: 2D DroneSchedulerPage 写 → 3D WindFarm3DView 读
 * 模式: 与 copilotStore.ts 一致 (zustand v5 create)
 */

import { create } from 'zustand';
import type { Turbine, Drone } from '../types';

export interface Drone3DState {
  // ── 数据 (DroneSchedulerPage 写入) ──
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  hasPlan: boolean;
  isRunning: boolean;
  speedMultiplier: number;

  // ── 3D 视图专属 ──
  viewMode: 'overview' | 'detail';
  focusedTurbineId: number | null;

  // ── Actions ──
  setTurbines: (t: Turbine[]) => void;
  setDrones: (d: Drone[]) => void;
  setActiveFarm: (f: string | null) => void;
  setHasPlan: (v: boolean) => void;
  setIsRunning: (v: boolean) => void;
  setSpeedMultiplier: (v: number) => void;
  setViewMode: (m: 'overview' | 'detail') => void;
  focusTurbine: (id: number | null) => void;
}

export const useDrone3DStore = create<Drone3DState>((set) => ({
  turbines: [],
  drones: [],
  activeFarm: null,
  hasPlan: false,
  isRunning: false,
  speedMultiplier: 1,
  viewMode: 'overview',
  focusedTurbineId: null,

  setTurbines: (turbines) => set({ turbines }),
  setDrones: (drones) => set({ drones }),
  setActiveFarm: (activeFarm) => set({ activeFarm }),
  setHasPlan: (hasPlan) => set({ hasPlan }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setSpeedMultiplier: (speedMultiplier) => set({ speedMultiplier }),
  setViewMode: (viewMode) => set({ viewMode }),
  focusTurbine: (id) =>
    set({ focusedTurbineId: id, viewMode: id ? 'detail' : 'overview' }),
}));
