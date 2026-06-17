import { useMemo, useState } from 'react';
import { Html, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Turbine } from '../../../types';

interface Props {
  turbine: Turbine;
  isFocused: boolean;
  onFocus: (id: number) => void;
}

function createProceduralTurbine(): THREE.Group {
  const group = new THREE.Group();
  const towerMat = new THREE.MeshStandardMaterial({ color: '#e8e8e8', roughness: 0.4, metalness: 0.45 });

  const tower = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 2.2, 80, 16), towerMat);
  tower.position.y = 40;
  tower.castShadow = true;
  tower.receiveShadow = true;
  group.add(tower);

  const nacelle = new THREE.Mesh(new THREE.BoxGeometry(9, 3.6, 3.6), towerMat);
  nacelle.position.set(-2, 82, 0);
  nacelle.castShadow = true;
  group.add(nacelle);

  const hub = new THREE.Mesh(
    new THREE.SphereGeometry(2, 16, 16),
    new THREE.MeshStandardMaterial({ color: '#d7d7d7', roughness: 0.3, metalness: 0.55 }),
  );
  hub.position.set(2.5, 82, 0);
  group.add(hub);

  const bladesGroup = new THREE.Group();
  bladesGroup.position.set(2.5, 82, 0);
  bladesGroup.name = 'blades';
  for (let i = 0; i < 3; i += 1) {
    const blade = new THREE.Mesh(
      new THREE.BoxGeometry(0.55, 36, 1.7),
      new THREE.MeshStandardMaterial({ color: '#f7f7f7', roughness: 0.26, metalness: 0.25 }),
    );
    blade.position.y = 18;
    blade.rotation.z = (i * Math.PI * 2) / 3;
    blade.castShadow = true;
    bladesGroup.add(blade);
  }
  group.add(bladesGroup);

  return group;
}

function RealTurbineModel({ fallback }: { fallback: THREE.Group }) {
  const gltf = useGLTF('/models/wind-turbine.glb');
  const model = useMemo(() => {
    if (!gltf.scene) return fallback;
    const clone = gltf.scene.clone(true);
    const box = new THREE.Box3().setFromObject(clone);
    const size = new THREE.Vector3();
    box.getSize(size);
    const scale = 115 / Math.max(size.y, 1);
    clone.scale.setScalar(scale);
    clone.position.y = -box.min.y * scale;
    clone.rotation.y = Math.PI / 2;
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });
    return clone;
  }, [fallback, gltf.scene]);

  return <primitive object={model} />;
}

export default function TurbineInstance({ turbine, isFocused, onFocus }: Props) {
  const [hovered, setHovered] = useState(false);
  const proceduralModel = useMemo(() => createProceduralTurbine(), []);

  const [posX, , posZ] = gpsToScene(turbine.lat, turbine.lng, 0);
  const scale = 1 + ((turbine.power_mw || 3) - 2) * 0.12;
  const hiColor = turbine.hi_value >= 90 ? '#10B981' : turbine.hi_value >= 70 ? '#F59E0B' : '#EF4444';
  const statusGlow = turbine.status === 'fault' ? '#ff3333' : turbine.status === 'warning' ? '#ffaa00' : '#3B82F6';

  return (
    <group position={[posX, 0, posZ]} scale={scale}>
      <group
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
        onClick={(e) => {
          e.stopPropagation();
          onFocus(turbine.id);
        }}
      >
        <RealTurbineModel fallback={proceduralModel} />
      </group>

      <mesh position={[0, 0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.5, 3, 32]} />
        <meshBasicMaterial color={hiColor} side={THREE.DoubleSide} />
      </mesh>

      <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.2, 4.2, 32]} />
        <meshBasicMaterial
          color={statusGlow}
          side={THREE.DoubleSide}
          transparent
          opacity={hovered || isFocused ? 0.45 : 0.2}
        />
      </mesh>

      {hovered && (
        <Html position={[0, 120, 0]} center distanceFactor={15}>
          <div style={{
            background: 'rgba(13,36,71,0.95)',
            border: '1px solid rgba(59,130,246,0.4)',
            borderRadius: 8,
            padding: '8px 12px',
            color: '#f1f5f9',
            fontSize: 11,
            fontFamily: 'sans-serif',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}>
            <div style={{ fontWeight: 700 }}>{turbine.name}</div>
            <div style={{ color: '#94a3b8' }}>
              HI: {turbine.hi_value.toFixed(0)} | {turbine.power_mw}MW | {turbine.region}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}

useGLTF.preload('/models/wind-turbine.glb');
