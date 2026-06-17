/**
 * 特写场景: 聚焦单风机 + 关联无人机 + 路径
 */

import { useDrone3DStore } from '../../../services/drone3dStore';
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
  const relatedDrones = focused
    ? drones.filter((d) => d.assignedTurbines.includes(focused.id))
    : [];

  return (
    <>
      <TerrainSurface />

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
