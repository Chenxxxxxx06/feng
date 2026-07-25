import { useMemo, useRef } from 'react';
import { Html, useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone, InspectionTargetPart, InspectionWaypoint, Turbine } from '../../../types';

const PART_LABELS: Record<InspectionTargetPart, string> = {
  blade_tip: '叶尖',
  blade_root: '叶根',
  leading_edge: '叶片前缘',
  trailing_edge: '叶片后缘',
  hub: '轮毂',
  nacelle: '机舱',
};

function partLocalTarget(part: InspectionTargetPart): THREE.Vector3 {
  const targets: Record<InspectionTargetPart, [number, number, number]> = {
    blade_tip: [2, 115, 0],
    blade_root: [2, 86, 0],
    leading_edge: [2, 104, -8],
    trailing_edge: [2, 104, 8],
    hub: [2, 82, 0],
    nacelle: [-3, 84, 0],
  };
  return new THREE.Vector3(...targets[part]);
}

function directionBetween(from: THREE.Vector3, to: THREE.Vector3) {
  const direction = new THREE.Vector3().subVectors(to, from);
  return direction.lengthSq() > 0 ? direction.normalize() : new THREE.Vector3(1, 0, 0);
}

function horizontalYaw(from: THREE.Vector3, to: THREE.Vector3) {
  return Math.atan2(to.x - from.x, to.z - from.z);
}

function routePoint(path: THREE.Vector3[], progress: number) {
  if (path.length === 0) return new THREE.Vector3();
  if (path.length === 1) return path[0].clone();
  const seg = Math.min(Math.floor(progress), path.length - 2);
  const frac = Math.max(0, Math.min(progress - seg, 1));
  const a = path[seg];
  const b = path[seg + 1];
  return a.clone().lerp(b, frac);
}

function nearestAssignedTarget(
  drone: Drone,
  turbines: Turbine[],
  position: THREE.Vector3,
  part: InspectionTargetPart,
) {
  const assigned = turbines.filter((t) => drone.assignedTurbines.includes(t.id));
  if (assigned.length === 0) return position.clone().add(new THREE.Vector3(20, 0, 0));

  let best = assigned[0];
  let bestDist = Infinity;
  for (const turbine of assigned) {
    const [x, , z] = gpsToScene(turbine.lat, turbine.lng, 0);
    const target = new THREE.Vector3(x, 0, z).add(partLocalTarget(part));
    const dist = target.distanceToSquared(position);
    if (dist < bestDist) {
      best = turbine;
      bestDist = dist;
    }
  }

  const [x, , z] = gpsToScene(best.lat, best.lng, 0);
  return new THREE.Vector3(x, 0, z).add(partLocalTarget(part));
}

function buildInspectionRoute(
  drone: Drone,
  _inspectionWaypoints: InspectionWaypoint[],
  fallbackAltitude: number,
) {
  return drone.path.map((p) => {
    const altitude = p.alt ?? fallbackAltitude;
    const [x, , z] = gpsToScene(p.lat, p.lng, altitude);
    return new THREE.Vector3(x, altitude, z);
  });
}

function RouteLine({ points, color }: { points: THREE.Vector3[]; color: string }) {
  const line = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.82 });
    return new THREE.Line(geometry, material);
  }, [points, color]);

  if (points.length < 2) return null;
  return <primitive object={line} />;
}

function RealDroneModel({ color }: { color: string }) {
  const gltf = useGLTF('/models/drone.glb');
  const model = useMemo(() => {
    const clone = gltf.scene.clone(true);
    const box = new THREE.Box3().setFromObject(clone);
    const size = new THREE.Vector3();
    box.getSize(size);
    const scale = 1.45 / Math.max(size.x, size.y, size.z, 1);
    clone.scale.setScalar(scale);
    clone.position.y = -box.min.y * scale;
    clone.rotation.y = Math.PI;
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        child.castShadow = true;
        const mat = (child as THREE.Mesh).material;
        if (Array.isArray(mat)) return;
        if (mat && 'emissive' in mat) {
          (mat as THREE.MeshStandardMaterial).emissive = new THREE.Color(color).multiplyScalar(0.08);
        }
      }
    });
    return clone;
  }, [color, gltf.scene]);

  return <primitive object={model} />;
}

function InspectionDrone({
  drone,
  route,
  turbines,
  part,
}: {
  drone: Drone;
  route: THREE.Vector3[];
  turbines: Turbine[];
  part: InspectionTargetPart;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const aimRef = useRef<THREE.Line>(null);
  const fovRef = useRef<THREE.Group>(null);
  const groundRangeRef = useRef<THREE.Mesh>(null);
  const color = drone.color || '#facc15';

  const aimLine = useMemo(() => {
    const geometry = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(1, 0, 0)]);
    const material = new THREE.LineBasicMaterial({ color: '#facc15', transparent: true, opacity: 0.95 });
    return new THREE.Line(geometry, material);
  }, []);

  useFrame(() => {
    if (!groupRef.current) return;
    const routeProgress = route.length > 1
      ? Math.min(drone.progress, route.length - 1.001)
      : 0;
    const position = routePoint(route, routeProgress);
    const target = nearestAssignedTarget(drone, turbines, position, part);
    const yaw = horizontalYaw(position, target);

    groupRef.current.position.copy(position);
    groupRef.current.rotation.set(0, yaw + Math.PI, 0);

    if (aimRef.current) {
      aimRef.current.geometry.dispose();
      aimRef.current.geometry = new THREE.BufferGeometry().setFromPoints([position, target]);
    }
    if (fovRef.current) {
      fovRef.current.position.copy(position);
      fovRef.current.quaternion.copy(
        new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), directionBetween(position, target)),
      );
    }
    if (groundRangeRef.current) {
      groundRangeRef.current.position.set(position.x, 0.8, position.z);
    }
  });

  return (
    <>
      <group ref={groupRef}>
        <RealDroneModel color={color} />
        <Html position={[0, 5.2, 0]} center distanceFactor={24}>
          <div style={{
            padding: '4px 7px',
            borderRadius: 6,
            border: `1px solid ${color}88`,
            background: 'rgba(8,18,34,0.86)',
            color: '#e5f2ff',
            fontSize: 10,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}>
            {drone.name} 拍摄 {PART_LABELS[part]}
          </div>
        </Html>
      </group>

      <primitive ref={aimRef} object={aimLine} />

      <group ref={fovRef}>
        <mesh position={[0, 9, 0]}>
          <coneGeometry args={[8, 24, 36, 1, true]} />
          <meshBasicMaterial color="#facc15" transparent opacity={0.16} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
        <mesh position={[0, 21, 0]}>
          <ringGeometry args={[7, 8, 48]} />
          <meshBasicMaterial color="#facc15" transparent opacity={0.42} side={THREE.DoubleSide} depthWrite={false} />
        </mesh>
      </group>

      <mesh ref={groundRangeRef} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[9, 11, 72]} />
        <meshBasicMaterial color="#facc15" transparent opacity={0.22} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </>
  );
}

export default function InspectionViewpoints() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const part = useDrone3DStore((s) => s.inspectionTargetPart);
  const inspectionWaypoints = useDrone3DStore((s) => s.inspectionWaypoints);

  const visibleTurbines = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm) : turbines,
    [activeFarm, turbines],
  );

  const visibleTurbineIds = useMemo(() => new Set(visibleTurbines.map((t) => t.id)), [visibleTurbines]);
  const visibleDrones = useMemo(
    () => drones.filter((d) => d.assignedTurbines.some((id) => visibleTurbineIds.has(id))),
    [drones, visibleTurbineIds],
  );

  if (visibleDrones.length === 0) return null;

  return (
    <group>
      {visibleDrones.map((drone) => {
        const altitude = drone._altitude ?? 70;
        const route = buildInspectionRoute(drone, inspectionWaypoints, altitude);
        return (
          <group key={drone.id}>
            <RouteLine points={route} color={drone.color} />
            {route.map((point, index) => {
              return (
                <mesh key={`${drone.id}-${index}`} position={point}>
                  <sphereGeometry args={[0.85, 14, 14]} />
                  <meshBasicMaterial color={drone.color} transparent opacity={0.42} />
                </mesh>
              );
            })}
            <InspectionDrone drone={drone} route={route} turbines={visibleTurbines} part={part} />
          </group>
        );
      })}
    </group>
  );
}

useGLTF.preload('/models/drone.glb');
