/**
 * 相机管理: OrbitControls + 总览↔特写切换动画
 * Esc 键返回总览, 双击空白返回总览
 */

import { useRef, useEffect } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { gpsToScene } from '../../../utils/coordinateTransform';

export default function CameraManager() {
  const controlsRef = useRef<any>(null);
  const { camera } = useThree();
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const turbines = useDrone3DStore((s) => s.turbines);

  const animating = useRef(false);
  const animProgress = useRef(0);
  const animDuration = 0.8;
  const startPos = useRef(new THREE.Vector3());
  const startTarget = useRef(new THREE.Vector3());
  const endPos = useRef(new THREE.Vector3());
  const endTarget = useRef(new THREE.Vector3());

  // 启动切换动画
  useEffect(() => {
    if (viewMode === 'detail' && focusedTurbineId) {
      const turbine = turbines.find((t) => t.id === focusedTurbineId);
      if (!turbine) return;
      const [tx, , tz] = gpsToScene(turbine.lat, turbine.lng);
      endPos.current.set(tx + 80, 60, tz + 80);
      endTarget.current.set(tx, 50, tz);
    } else {
      endPos.current.set(0, 400, 300);
      endTarget.current.set(0, 0, 0);
    }

    if (controlsRef.current) {
      startPos.current.copy(camera.position);
      startTarget.current.copy(controlsRef.current.target);
      animProgress.current = 0;
      animating.current = true;
    }
  }, [viewMode, focusedTurbineId, turbines, camera]);

  // 动画 update
  useFrame((_, delta) => {
    if (!animating.current || !controlsRef.current) return;
    animProgress.current += delta / animDuration;
    const t = Math.min(animProgress.current, 1);
    // ease-in-out
    const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    camera.position.lerpVectors(startPos.current, endPos.current, eased);
    controlsRef.current.target.lerpVectors(startTarget.current, endTarget.current, eased);
    controlsRef.current.update();
    if (t >= 1) animating.current = false;
  });

  // Esc 键返回
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') useDrone3DStore.getState().focusTurbine(null);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  return (
    <OrbitControls
      ref={controlsRef}
      enableDamping dampingFactor={0.08}
      minDistance={50} maxDistance={800}
      maxPolarAngle={Math.PI / 2.1}
      target={[0, 0, 0]}
    />
  );
}
