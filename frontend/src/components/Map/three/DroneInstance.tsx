/**
 * 无人机 3D 实例 — 实时位置 + 旋翼旋转 + 飞行姿态
 */

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
}

function createProceduralDrone(): THREE.Group {
  const group = new THREE.Group();

  // 机身
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(1.5, 0.4, 1.5),
    new THREE.MeshStandardMaterial({ color: '#333', roughness: 0.3, metalness: 0.7 }),
  );
  body.position.y = 0.2;
  body.castShadow = true;
  group.add(body);

  // 4 个旋翼臂 + 桨叶
  for (let i = 0; i < 4; i++) {
    const angle = (i * Math.PI) / 2 + Math.PI / 4;
    const arm = new THREE.Mesh(
      new THREE.CylinderGeometry(0.1, 0.1, 2.5, 6),
      new THREE.MeshStandardMaterial({ color: '#555', roughness: 0.4, metalness: 0.5 }),
    );
    arm.position.set(Math.cos(angle) * 1.2, 0.25, Math.sin(angle) * 1.2);
    arm.rotation.z = Math.PI / 2;
    arm.rotation.y = angle;
    arm.castShadow = true;
    group.add(arm);

    const propGroup = new THREE.Group();
    propGroup.position.set(Math.cos(angle) * 1.2, 0.35, Math.sin(angle) * 1.2);
    propGroup.name = `prop_${i}`;

    const prop1 = new THREE.Mesh(
      new THREE.BoxGeometry(2.5, 0.04, 0.2),
      new THREE.MeshStandardMaterial({ color: '#888', roughness: 0.2, metalness: 0.6 }),
    );
    propGroup.add(prop1);

    const prop2 = new THREE.Mesh(
      new THREE.BoxGeometry(0.2, 0.04, 2.5),
      new THREE.MeshStandardMaterial({ color: '#888', roughness: 0.2, metalness: 0.6 }),
    );
    propGroup.add(prop2);

    group.add(propGroup);
  }

  // 相机
  const cam = new THREE.Mesh(
    new THREE.SphereGeometry(0.18, 8, 8),
    new THREE.MeshStandardMaterial({ color: '#111', roughness: 0.2, metalness: 0.9 }),
  );
  cam.position.set(0, -0.15, 0.8);
  group.add(cam);

  return group;
}

export default function DroneInstance({ drone }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const propRefs = useRef<THREE.Object3D[]>([]);

  const model = useMemo(() => createProceduralDrone(), []);

  useMemo(() => {
    propRefs.current = [];
    model.traverse((c) => {
      if (c.name.startsWith('prop_')) propRefs.current.push(c);
    });
  }, [model]);

  const targetPos = useRef(new THREE.Vector3());
  const currentYaw = useRef(0);

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    // 位置
    if (drone.currentPosition) {
      const [tx, , tz] = gpsToScene(drone.currentPosition.lat, drone.currentPosition.lng);
      targetPos.current.set(tx, 50, tz);
      g.position.lerp(targetPos.current, 0.35);
    }

    // 朝向
    if (drone.path.length >= 2) {
      const seg = Math.min(Math.floor(drone.progress), drone.path.length - 2);
      const next = drone.path[seg + 1];
      const curr = drone.path[seg];
      const [nx] = gpsToScene(next.lat, next.lng);
      const [cx] = gpsToScene(curr.lat, curr.lng);
      const targetYaw = Math.atan2(nx - cx, g.position.z > 0 ? -1 : 1) + Math.PI / 2;
      currentYaw.current += (targetYaw - currentYaw.current) * 0.2;
      g.rotation.y = currentYaw.current;
      // 前倾
      g.rotation.x = -0.08;
    }

    // 旋翼
    const rpm = drone.status === 'flying' ? 800 : 0;
    propRefs.current.forEach((p) => {
      p.rotation.y += (rpm / 60) * Math.PI * 2 * delta;
    });
  });

  if (drone.status === 'idle' || drone.status === 'charging') return null;

  return (
    <group ref={groupRef}>
      <primitive object={model} />
    </group>
  );
}
