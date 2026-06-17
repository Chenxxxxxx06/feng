/**
 * 特写场景: 聚焦单风机 + 关联无人机 + 路径
 */

import { useMemo } from 'react';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { setCoordinateOrigin, computeTurbineBounds } from '../../../utils/coordinateTransform';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';
import DroneInstance from './DroneInstance';
import FlightPathLines from './FlightPathLines';

export default function DetailScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  const focused = turbines.find((t) => t.id === focusedTurbineId);

  const relatedDrones = useMemo(
    () => focused
      ? drones.filter((d) => d.assignedTurbines.includes(focused.id))
      : [],
    [drones, focused],
  );

  // 以聚焦风机为中心的小范围地形
  const terrainConfig = useMemo(() => {
    if (focused) {
      const bounds = computeTurbineBounds([focused]);
      if (bounds) {
        setCoordinateOrigin(bounds.centerLat, bounds.centerLng);
        return { width: 600, depth: 600 };
      }
    }
    return { width: 800, depth: 800 };
  }, [focused]);

  return (
    <>
      <TerrainSurface width={terrainConfig.width} depth={terrainConfig.depth} />

      {turbines.map((turbine) => (
        <TurbineInstance
          key={turbine.id}
          turbine={turbine}
          isFocused={turbine.id === focusedTurbineId}
          onFocus={focusTurbine}
        />
      ))}

      {relatedDrones.map((drone) => (
        <group key={drone.id}>
          <DroneInstance drone={drone} />
          <FlightPathLines drone={drone} />
        </group>
      ))}
    </>
  );
}
