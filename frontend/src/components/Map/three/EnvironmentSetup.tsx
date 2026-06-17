/**
 * 3D 场景环境: 光照 / 雾 / 天空
 * 陕北黄土高原色调 — 暖黄土雾 + 下午太阳光
 */

import { useThree } from '@react-three/fiber';
import { useEffect } from 'react';
import * as THREE from 'three';

export default function EnvironmentSetup() {
  const { scene } = useThree();

  useEffect(() => {
    scene.background = new THREE.Color('#7ec8e3');
    scene.fog = new THREE.Fog('#d4c48c', 600, 1400);
  }, [scene]);

  return (
    <>
      {/* 太阳光 + 阴影 */}
      <directionalLight
        position={[200, 350, 100]}
        color="#fff3e0"
        intensity={1.2}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={800}
        shadow-camera-left={-400}
        shadow-camera-right={400}
        shadow-camera-top={400}
        shadow-camera-bottom={-400}
      />

      {/* 环境光 */}
      <ambientLight color="#4a6c8f" intensity={0.6} />

      {/* 半球光 (天空+地面反射) */}
      <hemisphereLight
        color="#87CEEB"
        groundColor="#8B7355"
        intensity={0.4}
      />
    </>
  );
}
