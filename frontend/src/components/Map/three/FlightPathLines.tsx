/**
 * 3D 飞行路径线 — 已完成段(实线) + 未完成段(虚线)
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
}

export default function FlightPathLines({ drone }: Props) {
  const { completed, remaining, color } = useMemo(() => {
    if (drone.path.length < 2) return { completed: null, remaining: null, color: drone.color };

    const pts = drone.path.map((p) => {
      const [x, , z] = gpsToScene(p.lat, p.lng);
      return new THREE.Vector3(x, 50, z);
    });

    const idx = Math.floor(drone.progress);
    return {
      completed: pts.slice(0, idx + 1).length >= 2 ? pts.slice(0, idx + 1) : null,
      remaining: pts.slice(idx).length >= 2 ? pts.slice(idx) : null,
      color: drone.color,
    };
  }, [drone.path, drone.progress, drone.color]);

  return (
    <>
      {completed && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={completed.length}
              array={new Float32Array(completed.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} linewidth={1} transparent={false} />
        </line>
      )}

      {remaining && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={remaining.length}
              array={new Float32Array(remaining.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineDashedMaterial
            color={color} linewidth={1}
            opacity={0.4} transparent
            dashSize={12} gapSize={10}
          />
        </line>
      )}
    </>
  );
}
