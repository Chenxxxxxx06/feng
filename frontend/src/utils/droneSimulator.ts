/**
 * Drone Simulator — manages drone fleet state and animation updates.
 * Pure TypeScript, decoupled from React/Leaflet.
 */

import type { Drone, DroneFleetConfig, DroneSimState } from '../types';
import { solveTsp, solveVrp, haversine } from './dronePathPlanner';
import type { Point, VrpResult, TspResult } from './dronePathPlanner';

// Re-export haversine for DroneMap
export { haversine } from './dronePathPlanner';

export const DRONE_COLORS = [
  '#f0883e', '#388bfd', '#a371f7', '#39d2c0', '#f85149', '#d29922', '#3fb950',
  '#ff69b4', '#00d4aa', '#ff6b6b', '#48dbfb', '#feca57',
];

export function createDefaultConfig(): DroneFleetConfig {
  return { count: 3, range: 30_000, speed: 15 };
}

export function createInitialState(config?: DroneFleetConfig): DroneSimState {
  const cfg = config || createDefaultConfig();
  return {
    fleet: [],
    config: cfg,
    mode: 'vrp',
    activeFarm: null,
    isRunning: false,
    speedMultiplier: 1,
    totalTurbines: 0,
    completedTurbines: 0,
    elapsedTime: 0,
  };
}

/**
 * Build drone fleet from a VRP or TSP result.
 */
export function buildFleet(
  result: TspResult | VrpResult,
  config: DroneFleetConfig,
  farmName: string,
): Drone[] {
  // Single TSP result
  if ('path' in result && !('assignments' in result)) {
    const drone: Drone = {
      id: 1,
      name: `Drone-1`,
      status: 'idle',
      battery: 100,
      range: config.range,
      speed: config.speed,
      color: DRONE_COLORS[0],
      assignedTurbines: result.path.map((p) => p.id ?? 0).filter((id) => id > 0),
      completedTurbines: result.path[0]?.id ? [result.path[0].id] : [],
      currentPosition: result.path[0] ? { lat: result.path[0].lat, lng: result.path[0].lng } : null,
      path: result.path.map((p) => ({ lat: p.lat, lng: p.lng })),
      progress: 0,
    };
    return [drone];
  }

  // VRP result
  const vrp = result as VrpResult;
  return vrp.assignments.map((a) => {
    const firstPoint = a.path.path[0];
    return {
      id: a.droneIndex + 1,
      name: `Drone-${a.droneIndex + 1}`,
      status: 'idle' as const,
      battery: 100,
      range: config.range,
      speed: config.speed,
      color: a.color,
      assignedTurbines: a.turbines.map((p) => p.id ?? 0).filter((id) => id > 0),
      completedTurbines: firstPoint?.id ? [firstPoint.id] : [],
      currentPosition: firstPoint ? { lat: firstPoint.lat, lng: firstPoint.lng } : null,
      path: a.path.path.map((p) => ({ lat: p.lat, lng: p.lng })),
      progress: 0,
    };
  });
}

/**
 * Advance simulation by one tick.
 * Returns updated fleet state and whether simulation is complete.
 */
export function tickSimulation(
  fleet: Drone[],
  dt: number,          // real seconds elapsed
  speedMultiplier: number,
): { fleet: Drone[]; allComplete: boolean; completedThisTick: number } {
  const simulatedDt = dt * speedMultiplier;
  let completedThisTick = 0;

  const newFleet = fleet.map((drone) => {
    if (drone.status === 'idle' && drone.path.length > 0) {
      return { ...drone, status: 'flying' as const };
    }
    if (drone.status !== 'flying' || drone.path.length < 2) {
      // Single-turbine or empty path: immediately complete
      if (drone.status === 'flying' && drone.path.length < 2) {
        return {
          ...drone,
          status: 'returning' as const,
          completedTurbines: [...drone.assignedTurbines],
          progress: drone.path.length,
        };
      }
      return drone;
    }

    const speed = drone.speed; // m/s
    const distPerTick = speed * simulatedDt;
    let { progress } = drone;
    let remaining = distPerTick;
    let allDone = false;

    // Move along path segments
    let segmentStart = Math.floor(progress);
    let segmentFrac = progress - segmentStart;

    while (remaining > 0 && !allDone) {
      if (segmentStart >= drone.path.length - 1) {
        allDone = true;
        break;
      }

      const p1 = drone.path[segmentStart];
      const p2 = drone.path[segmentStart + 1];
      const segLen = haversine(
        { lat: p1.lat, lng: p1.lng },
        { lat: p2.lat, lng: p2.lng },
      );
      const remainingInSegment = segLen * (1 - segmentFrac);

      if (remaining >= remainingInSegment) {
        remaining -= remainingInSegment;
        segmentStart += 1;
        segmentFrac = 0;
      } else {
        segmentFrac += remaining / segLen;
        remaining = 0;
      }
    }

    const newProgress = segmentStart + segmentFrac;

    // Determine which turbines were completed in this tick
    const oldSeg = Math.floor(progress);
    const newSeg = Math.floor(newProgress);
    const newlyCompleted: number[] = [];
    for (let s = oldSeg + 1; s <= newSeg && s < drone.path.length; s += 1) {
      const turbineId = drone.assignedTurbines[s];
      if (turbineId && !drone.completedTurbines.includes(turbineId)) {
        newlyCompleted.push(turbineId);
      }
    }

    const allSegmentsDone = newProgress >= drone.path.length - 1;
    const completed = [...drone.completedTurbines, ...newlyCompleted];
    completedThisTick += newlyCompleted.length;

    // Calculate current position
    const seg = Math.min(Math.floor(newProgress), drone.path.length - 2);
    const frac = newProgress - seg;
    const currentPos = drone.path.length > 0
      ? {
          lat: drone.path[seg].lat + (drone.path[Math.min(seg + 1, drone.path.length - 1)].lat - drone.path[seg].lat) * frac,
          lng: drone.path[seg].lng + (drone.path[Math.min(seg + 1, drone.path.length - 1)].lng - drone.path[seg].lng) * frac,
        }
      : drone.currentPosition;

    const batteryDrain = (speed * simulatedDt) / drone.range * 100;
    const newBattery = Math.max(0, drone.battery - batteryDrain);

    return {
      ...drone,
      progress: Math.min(newProgress, drone.path.length - 1 + 0.001),
      currentPosition: currentPos,
      completedTurbines: completed,
      battery: newBattery,
      status: allSegmentsDone ? ('returning' as const) : ('flying' as const),
    };
  });

  const allComplete = newFleet.every(
    (d) => d.status === 'returning' || (d.status === 'idle' && d.path.length === 0),
  );

  return { fleet: newFleet, allComplete, completedThisTick };
}

/**
 * Interpolate drone position for smooth rendering between ticks.
 */
export function interpolatePosition(
  drone: Drone,
  _globalProgress: number,
): { lat: number; lng: number } | null {
  return drone.currentPosition;
}
