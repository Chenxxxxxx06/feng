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
        color="#fff8e7"
        intensity={1.5}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={800}
        shadow-camera-left={-400}
        shadow-camera-right={400}
        shadow-camera-top={400}
        shadow-camera-bottom={-400}
      />

      {/* 环境光 — 提高确保场景永远可见 */}
      <ambientLight color="#ffffff" intensity={0.9} />

      {/* 半球光 */}
      <hemisphereLight
        color="#b1e1ff"
        groundColor="#8B7355"
        intensity={0.7}
      />

      {/* 调试辅助网格 (2000m × 2000m, 100m 间距) */}
      <gridHelper args={[2000, 20, '#888888', '#444444']} position={[0, 0.5, 0]} />
    </>
  );
}
