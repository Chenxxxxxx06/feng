/**
 * 特写场景: 聚焦单风机 + 关联无人机 + 路径
 */

import { useMemo } from 'react';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { setCoordinateOrigin, computeTurbineBounds } from '../../../utils/coordinateTransform';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';

export default function DetailScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  const focused = turbines.find((t) => t.id === focusedTurbineId);
  const visibleTurbines = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm) : turbines,
    [activeFarm, turbines],
  );

  // 以聚焦风机为中心的小范围地形
  const terrainConfig = useMemo(() => {
    const bounds = computeTurbineBounds(visibleTurbines);
    if (bounds) {
      setCoordinateOrigin(bounds.centerLat, bounds.centerLng);
      const size = Math.max(bounds.extentM * 1.25, 900);
      return { width: size, depth: size };
    }
    return { width: 900, depth: 900 };
  }, [visibleTurbines]);

  return (
    <>
      <TerrainSurface width={terrainConfig.width} depth={terrainConfig.depth} />

      {visibleTurbines.map((turbine) => (
        <TurbineInstance
          key={turbine.id}
          turbine={turbine}
          isFocused={turbine.id === focused?.id}
          onFocus={focusTurbine}
        />
      ))}
    </>
  );
}
