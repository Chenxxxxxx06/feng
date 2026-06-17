import { useMemo } from 'react';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { setCoordinateOrigin, computeTurbineBounds } from '../../../utils/coordinateTransform';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';

export default function OverviewScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  const visibleTurbines = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm) : turbines,
    [turbines, activeFarm],
  );

  const terrainConfig = useMemo(() => {
    const bounds = computeTurbineBounds(visibleTurbines);
    if (bounds) {
      setCoordinateOrigin(bounds.centerLat, bounds.centerLng);
      const size = Math.max(bounds.extentM * 1.6, 800);
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

    </>
  );
}
