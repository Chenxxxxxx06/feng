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
import InspectionViewpoints from './InspectionViewpoints';

export default function WindFarm3DView() {
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const noFlyZones = useDrone3DStore((s) => s.noFlyZones);
  const showNoFlyZones = useDrone3DStore((s) => s.showNoFlyZones);

  if (!activeFarm) {
    return (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          overflow: 'hidden',
          backgroundImage: 'linear-gradient(120deg, rgba(7, 26, 53, 0.8), rgba(7, 26, 53, 0.42)), url(/login-bg.jpg)',
          backgroundPosition: 'center',
          backgroundSize: 'cover',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'radial-gradient(circle at 70% 20%, rgba(59,130,246,0.22), transparent 34%), linear-gradient(180deg, transparent 0%, rgba(3,8,18,0.48) 100%)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 24,
            bottom: 24,
            maxWidth: 'calc(100% - 48px)',
            color: '#dbeafe',
            textShadow: '0 2px 18px rgba(0,0,0,0.55)',
          }}
        >
          <div style={{ fontSize: 12, color: '#7dd3fc', letterSpacing: 1.5, marginBottom: 8 }}>
            UAV INSPECTION
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 8 }}>
            无人机巡检任务预览
          </div>
          <div style={{ fontSize: 12, lineHeight: 1.7, color: '#cbd5e1', whiteSpace: 'nowrap' }}>
            选择左侧风场后，将加载对应风机、起降点、航线和拍摄范围。
          </div>
        </div>
      </div>
    );
  }

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
          <InspectionViewpoints />
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
