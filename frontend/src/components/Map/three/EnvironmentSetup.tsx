import { useThree } from '@react-three/fiber';
import { useEffect } from 'react';
import * as THREE from 'three';

export default function EnvironmentSetup() {
  const { scene, gl } = useThree();

  useEffect(() => {
    scene.background = new THREE.Color('#b8d7e8');
    scene.fog = new THREE.FogExp2('#c9d5c2', 0.00042);
    gl.toneMapping = THREE.ACESFilmicToneMapping;
    gl.toneMappingExposure = 1.08;
  }, [gl, scene]);

  return (
    <>
      <directionalLight
        position={[260, 420, 180]}
        color="#fff3d0"
        intensity={2.15}
        castShadow
        shadow-mapSize-width={4096}
        shadow-mapSize-height={4096}
        shadow-camera-far={1400}
        shadow-camera-left={-700}
        shadow-camera-right={700}
        shadow-camera-top={700}
        shadow-camera-bottom={-700}
      />

      <ambientLight color="#e8f3ff" intensity={0.55} />

      <hemisphereLight
        color="#c9e8ff"
        groundColor="#7a6d4f"
        intensity={1.1}
      />

      <mesh position={[0, -18, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[9000, 96]} />
        <meshBasicMaterial color="#9fad86" transparent opacity={0.28} depthWrite={false} />
      </mesh>
    </>
  );
}
