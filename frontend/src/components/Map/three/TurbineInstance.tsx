/**
 * 单个风机 3D 实例
 * 位置: GPS → 3D 场景坐标 | 状态: 颜色映射 | 动画: 叶片旋转
 * 优先 GLTF 模型, 失败 fallback 程序化几何体
 */

import { useRef, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Turbine } from '../../../types';

interface Props {
  turbine: Turbine;
  isFocused: boolean;
  onFocus: (id: number) => void;
}

/** 程序化风机 (GLTF 不可用时使用) */
function createProceduralTurbine(): THREE.Group {
  const group = new THREE.Group();

  // 塔筒
  const towerGeo = new THREE.CylinderGeometry(1.5, 2.2, 80, 8);
  const towerMat = new THREE.MeshStandardMaterial({
    color: '#e8e8e8', roughness: 0.4, metalness: 0.6,
  });
  const tower = new THREE.Mesh(towerGeo, towerMat);
  tower.position.y = 40;
  tower.castShadow = true;
  tower.receiveShadow = true;
  group.add(tower);

  // 机舱
  const nacelleGeo = new THREE.BoxGeometry(8, 3.5, 3.5);
  const nacelle = new THREE.Mesh(nacelleGeo, towerMat);
  nacelle.position.y = 82;
  nacelle.castShadow = true;
  group.add(nacelle);

  // 轮毂
  const hub = new THREE.Mesh(
    new THREE.SphereGeometry(1.8, 8, 8),
    new THREE.MeshStandardMaterial({ color: '#ccc', roughness: 0.3, metalness: 0.8 }),
  );
  hub.position.set(2, 82, 0);
  hub.name = 'hub';
  group.add(hub);

  // 叶片组
  const bladesGroup = new THREE.Group();
  bladesGroup.position.set(2, 82, 0);
  bladesGroup.name = 'blades';
  for (let i = 0; i < 3; i++) {
    const bladeGeo = new THREE.BoxGeometry(0.6, 35, 1.8);
    const blade = new THREE.Mesh(bladeGeo,
      new THREE.MeshStandardMaterial({ color: '#f5f5f5', roughness: 0.3, metalness: 0.5 }),
    );
    blade.position.y = 17;
    blade.rotation.z = (i * Math.PI * 2) / 3;
    blade.castShadow = true;
    blade.name = `blade_${i}`;
    bladesGroup.add(blade);
  }
  group.add(bladesGroup);

  return group;
}

export default function TurbineInstance({ turbine, isFocused, onFocus }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const bladesRef = useRef<THREE.Group | null>(null);
  const [hovered, setHovered] = useState(false);

  const [posX, , posZ] = gpsToScene(turbine.lat, turbine.lng, 0);

  const scl = 0.85 + ((turbine.power_mw || 3) - 2) * 0.15;

  const hiColor =
    turbine.hi_value >= 90 ? '#10B981' :
    turbine.hi_value >= 70 ? '#F59E0B' : '#EF4444';

  const statusGlow =
    turbine.status === 'fault' ? '#ff3333' :
    turbine.status === 'warning' ? '#ffaa00' : '#3B82F6';

  const proceduralModel = useMemo(() => createProceduralTurbine(), []);

  // 收集 blades ref
  const modelRef = useRef<THREE.Group | null>(null);
  const setModelRef = (g: THREE.Group | null) => {
    modelRef.current = g;
    if (g) {
      g.traverse((child) => {
        if (child.name === 'blades') bladesRef.current = child as THREE.Group;
      });
    }
  };

  // 叶片旋转
  useFrame((_, delta) => {
    if (!bladesRef.current || turbine.status === 'fault') return;
    const rpm = turbine.status === 'warning' ? 6 : 12;
    bladesRef.current.rotation.z += (rpm / 60) * Math.PI * 2 * delta;
  });

  const opacity = isFocused ? 1 : 1; // 非聚焦风机 opacity 由场景层控制

  return (
    <group ref={groupRef} position={[posX, 0, posZ]} scale={scl}>
      {/* 风机顶部黄色标记球 — 验证位置正确 */}
      <mesh position={[0, 85, 0]}>
        <sphereGeometry args={[4, 8, 8]} />
        <meshBasicMaterial color="yellow" />
      </mesh>
      <group
        ref={setModelRef}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
        onClick={(e: { stopPropagation: () => void }) => {
          e.stopPropagation();
          onFocus(turbine.id);
        }}
      >
        <primitive object={proceduralModel} />
      </group>

      {/* HI 底座环 */}
      <mesh position={[0, 0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.5, 3, 32]} />
        <meshBasicMaterial color={hiColor} side={THREE.DoubleSide} />
      </mesh>

      {/* 状态发光环 */}
      <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.2, 4.2, 32]} />
        <meshBasicMaterial
          color={statusGlow} side={THREE.DoubleSide}
          transparent opacity={hovered || isFocused ? 0.45 : 0.2}
        />
      </mesh>

      {/* Hover 浮窗 */}
      {hovered && (
        <Html position={[0, 90, 0]} center distanceFactor={15}>
          <div style={{
            background: 'rgba(13,36,71,0.95)',
            border: '1px solid rgba(59,130,246,0.4)',
            borderRadius: '8px', padding: '8px 12px',
            color: '#F1F5F9', fontSize: '11px',
            fontFamily: 'sans-serif', whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}>
            <div style={{ fontWeight: 700 }}>{turbine.name}</div>
            <div style={{ color: '#94A3B8' }}>
              HI: {turbine.hi_value.toFixed(0)} | {turbine.power_mw}MW | {turbine.region}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}
