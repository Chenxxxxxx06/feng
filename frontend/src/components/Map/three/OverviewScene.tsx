/**
 * 总览场景: 动态地形 + 风机群 + 无人机群 + 路径线
 * 根据 activeFarm 自动计算坐标原点和地形范围
 */

import { useMemo } from 'react';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { setCoordinateOrigin, computeTurbineBounds } from '../../../utils/coordinateTransform';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';
import DroneInstance from './DroneInstance';
import FlightPathLines from './FlightPathLines';

export default function OverviewScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);
  const cruiseAltitude = useDrone3DStore((s) => s.cruiseAltitude);

  const visibleTurbines = useMemo(
    () => activeFarm
      ? turbines.filter((t) => t.region === activeFarm)
      : turbines,
    [turbines, activeFarm],
  );

  // 动态计算坐标原点 + 地形尺寸
  const terrainConfig = useMemo(() => {
    const bounds = computeTurbineBounds(visibleTurbines);
    if (bounds) {
      setCoordinateOrigin(bounds.centerLat, bounds.centerLng);
      const padding = 1.6;
      const size = Math.max(bounds.extentM * padding, 800);
      return { width: size, depth: size };
    }
    return { width: 800, depth: 800 };
  }, [visibleTurbines]);

  return (
    <>
      <TerrainSurface width={terrainConfig.width} depth={terrainConfig.depth} />

      {visibleTurbines.map((turbine) => (
        <TurbineInstance
          key={turbine.id}
          turbine={turbine}
          isFocused={false}
          onFocus={focusTurbine}
        />
      ))}

      {drones.map((drone) => (
        <DroneInstance key={drone.id} drone={drone} />
      ))}

      {drones.map((drone) => (
        <FlightPathLines key={`path-${drone.id}`} drone={drone} cruiseAltitude={cruiseAltitude} />
      ))}
    </>
  );
}
