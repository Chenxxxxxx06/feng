/**
 * NoFlyZoneVisual — 3D禁飞区可视化
 * 半透明红色盒体 + 边框线 + 标签
 * 从GPS坐标映射到3D场景
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { NoFlyZone } from '../../../types';

interface Props {
  zones: NoFlyZone[];
  opacity?: number;
}

export default function NoFlyZoneVisual({ zones, opacity = 0.25 }: Props) {
  return (
    <>
      {zones.map((zone, idx) => (
        <NoFlyZoneBox key={idx} zone={zone} opacity={opacity} />
      ))}
    </>
  );
}

function NoFlyZoneBox({ zone, opacity }: { zone: NoFlyZone; opacity: number }) {
  const { position, size } = useMemo(() => {
    const centerLat = (zone.south_lat + zone.north_lat) / 2;
    const centerLng = (zone.west_lng + zone.east_lng) / 2;
    const [cx, , cz] = gpsToScene(centerLat, centerLng, 0);

    const [swX, , swZ] = gpsToScene(zone.south_lat, zone.west_lng, 0);
    const [neX, , neZ] = gpsToScene(zone.north_lat, zone.east_lng, 0);

    const width = Math.abs(neX - swX);
    const depth = Math.abs(neZ - swZ);
    const height = zone.max_altitude - zone.min_altitude;
    const y = zone.min_altitude + height / 2;

    return {
      position: new THREE.Vector3(cx, y, cz),
      size: new THREE.Vector3(width, height, depth),
    };
  }, [zone]);

  return (
    <group position={position}>
      {/* 半透明填充盒 */}
      <mesh>
        <boxGeometry args={[size.x, size.y, size.z]} />
        <meshStandardMaterial
          color="#ef4444"
          transparent
          opacity={opacity}
          roughness={0.6}
          metalness={0.1}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* 边框线 (12条边) */}
      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(size.x, size.y, size.z)]} />
        <lineBasicMaterial color="#ef4444" transparent opacity={0.7} linewidth={1} />
      </lineSegments>

      {/* 顶面更强色 */}
      <mesh position={[0, size.y / 2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[size.x, size.z]} />
        <meshBasicMaterial color="#ff0000" transparent opacity={0.12} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </group>
  );
}
