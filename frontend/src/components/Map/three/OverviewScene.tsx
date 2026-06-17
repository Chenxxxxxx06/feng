/**
 * 总览场景: 地形 + 风机群 + 无人机群 + 路径线
 */

import { useDrone3DStore } from '../../../services/drone3dStore';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';
import DroneInstance from './DroneInstance';
import FlightPathLines from './FlightPathLines';

export default function OverviewScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  const visibleTurbines = activeFarm
    ? turbines.filter((t) => t.region === activeFarm)
    : turbines;

  return (
    <>
      <TerrainSurface />

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
        <FlightPathLines key={`path-${drone.id}`} drone={drone} />
      ))}
    </>
  );
}
