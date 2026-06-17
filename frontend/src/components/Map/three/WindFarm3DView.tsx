/**
 * 3D 风场视图入口 — react-three-fiber <Canvas> + HUD覆盖层
 * 集成: 环境/相机/场景/禁飞区/HUD面板
 */

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useDrone3DStore } from '../../../services/drone3dStore';
import EnvironmentSetup from './EnvironmentSetup';
import OverviewScene from './OverviewScene';
import DetailScene from './DetailScene';
import CameraManager from './CameraManager';
import NoFlyZoneVisual from './NoFlyZoneVisual';
import SceneHUD from './SceneHUD';

export default function WindFarm3DView() {
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const noFlyZones = useDrone3DStore((s) => s.noFlyZones);
  const showNoFlyZones = useDrone3DStore((s) => s.showNoFlyZones);

  return (
    <div style={{ position: 'absolute', inset: 0, background: '#071A35' }}>
      <Canvas
        style={{ position: 'absolute', inset: 0 }}
        camera={{ position: [0, 400, 300], fov: 55, near: 1, far: 50000 }}
        shadows
        gl={{
          antialias: true,
          powerPreference: 'high-performance',
        }}
        onCreated={({ gl }) => gl.setClearColor('#7ec8e3')}
      >
        <Suspense fallback={null}>
          <EnvironmentSetup />
          <CameraManager />
          {viewMode === 'overview' ? <OverviewScene /> : <DetailScene />}
          {/* 禁飞区3D可视化 */}
          {showNoFlyZones && noFlyZones.length > 0 && (
            <NoFlyZoneVisual zones={noFlyZones} />
          )}
        </Suspense>
      </Canvas>

      {/* HUD 覆盖层 */}
      <SceneHUD />
    </div>
  );
}
