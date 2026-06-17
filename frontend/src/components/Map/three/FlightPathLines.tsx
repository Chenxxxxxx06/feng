/**
 * 增强3D飞行路径 — 高度可视化 + 垂直地面投影线 + 分段颜色
 * 参考 AeroMind standalone.html 的路径渲染风格
 */

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
  cruiseAltitude?: number;
}

export default function FlightPathLines({ drone, cruiseAltitude = 50 }: Props) {
  const glowRef = useRef<THREE.Mesh>(null);

  const {
    completedPts,
    remainingPts,
    verticalLines,
    color,
  } = useMemo(() => {
    if (drone.path.length < 2) {
      return { completedPts: null, remainingPts: null, verticalLines: null, color: drone.color };
    }

    const pts = drone.path.map((p) => {
      const altitude = p.alt ?? cruiseAltitude;
      const [x, , z] = gpsToScene(p.lat, p.lng, altitude);
      return new THREE.Vector3(x, altitude, z);
    });

    const idx = Math.floor(drone.progress);

    // 地面投影点
    const groundPts = drone.path.map((p) => {
      const [x, , z] = gpsToScene(p.lat, p.lng);
      return new THREE.Vector3(x, 0, z);
    });

    // 垂直线 (每3个点画一条, 首尾必画)
    const vLines: { top: THREE.Vector3; bottom: THREE.Vector3 }[] = [];
    pts.forEach((pt, i) => {
      if (i % 3 === 0 || i === 0 || i === pts.length - 1) {
        vLines.push({ top: pt.clone(), bottom: new THREE.Vector3(pt.x, 0, pt.z) });
      }
    });

    return {
      completedPts: pts.slice(0, idx + 1).length >= 2 ? pts.slice(0, idx + 1) : null,
      remainingPts: pts.slice(idx).length >= 2 ? pts.slice(idx) : null,
      verticalLines: vLines,
      groundPts: groundPts.length >= 2 ? groundPts : null,
      color: drone.color,
    };
  }, [drone.path, drone.progress, drone.color, cruiseAltitude]);

  return (
    <>
      {/* ── 地面投影线 (虚线) ── */}
      {remainingPts && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={remainingPts.length}
              array={new Float32Array(remainingPts.flatMap((v) => [v.x, 0.5, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineDashedMaterial
            color={color}
            opacity={0.2}
            transparent
            dashSize={8}
            gapSize={6}
            linewidth={1}
          />
        </line>
      )}

      {/* ── 垂直投影线 (路径→地面) ── */}
      {verticalLines && verticalLines.map((vl, i) => (
        <line key={`vl-${i}`}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={2}
              array={new Float32Array([vl.top.x, vl.top.y, vl.top.z, vl.bottom.x, vl.bottom.y, vl.bottom.z])}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} transparent opacity={0.18} linewidth={1} />
        </line>
      ))}

      {/* ── 已完成段 (实线, 发光) ── */}
      {completedPts && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={completedPts.length}
              array={new Float32Array(completedPts.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} linewidth={2} transparent={false} />
        </line>
      )}

      {/* ── 未完成段 (虚线, 3D曲线) ── */}
      {remainingPts && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={remainingPts.length}
              array={new Float32Array(remainingPts.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineDashedMaterial
            color={color}
            linewidth={1.5}
            opacity={0.5}
            transparent
            dashSize={10}
            gapSize={8}
          />
        </line>
      )}

      {/* ── 路径点球 (关键航点) ── */}
      {drone.path.length > 0 && drone.path
        .filter((_, i) => i % 5 === 0 || i === 0 || i === drone.path.length - 1)
        .map((p, i) => {
          const altitude = p.alt ?? cruiseAltitude;
          const [x, , z] = gpsToScene(p.lat, p.lng);
          return (
            <mesh key={`wp-${i}`} position={[x, altitude, z]}>
              <sphereGeometry args={[1.2, 8, 8]} />
              <meshBasicMaterial color={color} transparent opacity={0.6} />
            </mesh>
          );
        })}
    </>
  );
}
