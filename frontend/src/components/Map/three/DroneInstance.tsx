/**
 * 增强无人机3D实例 — 精细程序化模型 + 旋翼旋转 + 飞行姿态 + LED指示灯
 * 参考 AeroMind drone-icon.svg 设计风格
 */

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import { useDrone3DStore } from '../../../services/drone3dStore';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
  showLabel?: boolean;
}

/** 创建精细程序化四旋翼无人机模型 */
function createDetailedDrone(droneColor: string): THREE.Group {
  const group = new THREE.Group();
  const bodyColor = droneColor;
  const accentColor = '#ffffff';
  const darkColor = '#1a1a2e';

  // ── 机身主体 (中心球体 + 延伸) ──
  const bodyGeo = new THREE.SphereGeometry(0.6, 16, 12);
  bodyGeo.scale(1, 0.6, 1.2);
  const bodyMat = new THREE.MeshStandardMaterial({
    color: darkColor, roughness: 0.25, metalness: 0.8,
  });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  body.position.y = 0.25;
  body.castShadow = true;
  group.add(body);

  // 顶部盖板
  const topPlate = new THREE.Mesh(
    new THREE.CylinderGeometry(0.5, 0.55, 0.12, 16),
    new THREE.MeshStandardMaterial({ color: bodyColor, roughness: 0.3, metalness: 0.6 }),
  );
  topPlate.position.y = 0.55;
  topPlate.castShadow = true;
  group.add(topPlate);

  // ── 4 个旋翼臂 ──
  const armLength = 1.1;
  for (let i = 0; i < 4; i++) {
    const angle = (i * Math.PI) / 2 + Math.PI / 4;
    const dx = Math.cos(angle) * 0.7;
    const dz = Math.sin(angle) * 0.7;

    // 主臂
    const armGroup = new THREE.Group();
    armGroup.position.set(dx, 0.3, dz);
    armGroup.rotation.y = -angle + Math.PI / 2;

    const armGeo = new THREE.CylinderGeometry(0.06, 0.08, armLength, 8);
    const arm = new THREE.Mesh(armGeo,
      new THREE.MeshStandardMaterial({ color: darkColor, roughness: 0.3, metalness: 0.7 }),
    );
    arm.rotation.z = Math.PI / 2;
    arm.castShadow = true;
    armGroup.add(arm);

    // 电机座
    const motorHousing = new THREE.Mesh(
      new THREE.CylinderGeometry(0.12, 0.14, 0.18, 12),
      new THREE.MeshStandardMaterial({ color: accentColor, roughness: 0.2, metalness: 0.5 }),
    );
    motorHousing.position.set(armLength / 2, 0, 0);
    armGroup.add(motorHousing);

    // 旋翼组
    const propGroup = new THREE.Group();
    propGroup.position.set(armLength / 2, 0.05, 0);
    propGroup.name = `prop_${i}`;

    // 双桨叶
    for (let j = 0; j < 2; j++) {
      const blade = new THREE.Mesh(
        new THREE.BoxGeometry(armLength * 0.7, 0.025, 0.18),
        new THREE.MeshStandardMaterial({ color: '#ddd', roughness: 0.15, metalness: 0.4 }),
      );
      blade.rotation.y = j * Math.PI / 2;
      propGroup.add(blade);
    }

    // 桨叶尖端标记
    const tipMarker1 = new THREE.Mesh(
      new THREE.BoxGeometry(0.12, 0.03, 0.2),
      new THREE.MeshStandardMaterial({ color: bodyColor, roughness: 0.2, metalness: 0.3, emissive: bodyColor, emissiveIntensity: 0.3 }),
    );
    tipMarker1.position.set(armLength * 0.32, 0, 0);
    propGroup.add(tipMarker1);

    armGroup.add(propGroup);
    group.add(armGroup);
  }

  // ── LED 指示灯 ──
  // 前方 (白色)
  const frontLED = new THREE.Mesh(
    new THREE.SphereGeometry(0.06, 6, 6),
    new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#ffffff', emissiveIntensity: 1.5, roughness: 0.1 }),
  );
  frontLED.position.set(0, 0.2, 0.7);
  frontLED.name = 'led_front';
  group.add(frontLED);

  // 后方 (红色)
  const rearLED = new THREE.Mesh(
    new THREE.SphereGeometry(0.06, 6, 6),
    new THREE.MeshStandardMaterial({ color: '#ff3333', emissive: '#ff0000', emissiveIntensity: 1.2, roughness: 0.1 }),
  );
  rearLED.position.set(0, 0.2, -0.7);
  rearLED.name = 'led_rear';
  group.add(rearLED);

  // 左 (绿色), 右 (蓝色) — 导航灯
  const navLEDColors = ['#00ff00', '#0088ff'];
  const navLEDPositions: [number, number, number][] = [[-0.5, 0.15, 0], [0.5, 0.15, 0]];
  navLEDPositions.forEach((pos, idx) => {
    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.05, 6, 6),
      new THREE.MeshStandardMaterial({ color: navLEDColors[idx], emissive: navLEDColors[idx], emissiveIntensity: 1, roughness: 0.1 }),
    );
    led.position.set(...pos);
    group.add(led);
  });

  // ── 相机云台 (底部) ──
  const gimbalGroup = new THREE.Group();
  gimbalGroup.position.set(0, -0.15, 0.35);
  gimbalGroup.name = 'gimbal';

  const gimbalArm = new THREE.Mesh(
    new THREE.CylinderGeometry(0.04, 0.04, 0.25, 8),
    new THREE.MeshStandardMaterial({ color: '#444', roughness: 0.3, metalness: 0.9 }),
  );
  gimbalGroup.add(gimbalArm);

  const cameraBody = new THREE.Mesh(
    new THREE.SphereGeometry(0.12, 8, 8),
    new THREE.MeshStandardMaterial({ color: '#111', roughness: 0.15, metalness: 0.95 }),
  );
  cameraBody.position.y = -0.18;
  gimbalGroup.add(cameraBody);

  const lens = new THREE.Mesh(
    new THREE.CylinderGeometry(0.06, 0.07, 0.08, 8),
    new THREE.MeshStandardMaterial({ color: '#334', roughness: 0.1, metalness: 0.9, emissive: '#111133', emissiveIntensity: 0.3 }),
  );
  lens.position.y = -0.25;
  gimbalGroup.add(lens);

  group.add(gimbalGroup);

  // ── 起落架 ──
  for (let side = -1; side <= 1; side += 2) {
    const skidGroup = new THREE.Group();
    skidGroup.position.set(side * 0.35, -0.25, 0);

    const strut1 = new THREE.Mesh(
      new THREE.CylinderGeometry(0.03, 0.03, 0.3, 6),
      new THREE.MeshStandardMaterial({ color: '#333', roughness: 0.4, metalness: 0.6 }),
    );
    strut1.position.set(0, -0.08, 0.2);
    strut1.rotation.x = 0.3;
    skidGroup.add(strut1);

    const strut2 = new THREE.Mesh(
      new THREE.CylinderGeometry(0.03, 0.03, 0.3, 6),
      new THREE.MeshStandardMaterial({ color: '#333', roughness: 0.4, metalness: 0.6 }),
    );
    strut2.position.set(0, -0.08, -0.2);
    strut2.rotation.x = -0.3;
    skidGroup.add(strut2);

    const skid = new THREE.Mesh(
      new THREE.BoxGeometry(0.05, 0.04, 0.5),
      new THREE.MeshStandardMaterial({ color: '#555', roughness: 0.3, metalness: 0.7 }),
    );
    skid.position.y = -0.22;
    skidGroup.add(skid);

    group.add(skidGroup);
  }

  return group;
}

export default function DroneInstance({ drone, showLabel = true }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const propRefs = useRef<THREE.Object3D[]>([]);
  const ledRefs = useRef<{ front?: THREE.Mesh; rear?: THREE.Mesh }>({});
  const speedMultiplier = useDrone3DStore((s) => s.speedMultiplier);

  const model = useMemo(() => createDetailedDrone(drone.color), [drone.color]);

  // 收集旋翼和LED引用
  useMemo(() => {
    propRefs.current = [];
    model.traverse((c) => {
      if (c.name.startsWith('prop_')) propRefs.current.push(c);
      if (c.name === 'led_front') ledRefs.current.front = c as THREE.Mesh;
      if (c.name === 'led_rear') ledRefs.current.rear = c as THREE.Mesh;
    });
  }, [model]);

  const targetPos = useRef(new THREE.Vector3());
  const currentYaw = useRef(0);
  const currentPitch = useRef(0);
  const currentRoll = useRef(0);
  const ledBlinkRef = useRef(0);

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    // ── 位置平滑插值 ──
    if (drone.currentPosition) {
      const [tx, , tz] = gpsToScene(drone.currentPosition.lat, drone.currentPosition.lng);
      // 如果有3D路径则使用路径高度，否则默认飞行高度
      const alt = drone._altitude ?? 50;
      targetPos.current.set(tx, alt, tz);
      g.position.lerp(targetPos.current, 0.35);
    }

    // ── 朝向 (基于路径方向) ──
    if (drone.path.length >= 2) {
      const seg = Math.min(Math.floor(drone.progress), drone.path.length - 2);
      const next = drone.path[seg + 1];
      const curr = drone.path[seg];
      const [nx] = gpsToScene(next.lat, next.lng);
      const [cx, , cz] = gpsToScene(curr.lat, curr.lng);
      const [nx2, , nz2] = gpsToScene(next.lat, next.lng);
      const targetYaw = Math.atan2(nx2 - cx, nz2 - cz);
      currentYaw.current += (targetYaw - currentYaw.current) * 0.15;
      g.rotation.y = currentYaw.current;

      // 前倾 (飞行姿态)
      if (drone.status === 'flying') {
        currentPitch.current += (-0.12 - currentPitch.current) * 0.1;
      } else {
        currentPitch.current += (0 - currentPitch.current) * 0.1;
      }
      g.rotation.x = currentPitch.current;
    }

    // ── 旋翼旋转 ──
    const baseRPM = drone.status === 'flying' ? 600 :
                drone.status === 'returning' ? 500 : 0;
    const rpm = baseRPM * Math.max(speedMultiplier, 0.5);
    propRefs.current.forEach((p, i) => {
      // 相邻旋翼反向旋转
      const dir = i % 2 === 0 ? 1 : -1;
      p.rotation.y += dir * (rpm / 60) * Math.PI * 2 * delta;
    });

    // ── LED 闪烁 ──
    ledBlinkRef.current += delta;
    const blinkOn = Math.sin(ledBlinkRef.current * 4) > 0;
    if (ledRefs.current.rear) {
      const mat = (ledRefs.current.rear.material as THREE.MeshStandardMaterial);
      mat.emissiveIntensity = blinkOn ? 1.5 : 0.3;
    }
  });

  if (drone.status === 'idle' || drone.status === 'charging') return null;

  return (
    <group ref={groupRef}>
      <primitive object={model} />

      {/* 飞行标签 */}
      {showLabel && (
        <Html position={[0, 2.5, 0]} center distanceFactor={20} occlude>
          <div style={{
            background: 'rgba(0,0,0,0.75)',
            color: drone.color,
            padding: '2px 8px',
            borderRadius: '10px',
            fontSize: '10px',
            fontFamily: 'monospace',
            whiteSpace: 'nowrap',
            border: `1px solid ${drone.color}44`,
            pointerEvents: 'none',
          }}>
            {drone.name} 🔋{drone.battery.toFixed(0)}%
          </div>
        </Html>
      )}

      {/* 地面投影阴影圆 */}
      <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.4, 0.8, 24]} />
        <meshBasicMaterial color="#000" transparent opacity={0.15} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}
