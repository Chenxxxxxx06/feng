/**
 * 3D 风场视图入口 — react-three-fiber <Canvas> + 覆盖层
 */

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useDrone3DStore } from '../../../services/drone3dStore';
import EnvironmentSetup from './EnvironmentSetup';
import OverviewScene from './OverviewScene';
import DetailScene from './DetailScene';
import CameraManager from './CameraManager';

export default function WindFarm3DView() {
  const viewMode = useDrone3DStore((s) => s.viewMode);

  return (
    <div style={{ width: '100%', height: '100%', background: '#071A35' }}>
      <Canvas
        camera={{ position: [0, 400, 300], fov: 50, near: 1, far: 2000 }}
        shadows
        gl={{ antialias: true }}
        onCreated={({ gl }) => gl.setClearColor('#7ec8e3')}
      >
        <Suspense fallback={null}>
          <EnvironmentSetup />
          <CameraManager />
          {viewMode === 'overview' ? <OverviewScene /> : <DetailScene />}
        </Suspense>
      </Canvas>

      <Overlay />
    </div>
  );
}

function Overlay() {
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);
  const turbines = useDrone3DStore((s) => s.turbines);
  const focused = turbines.find((t) => t.id === focusedTurbineId);

  return (
    <div style={{
      position: 'absolute', top: 12, left: 12, zIndex: 10,
      display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      {/* 图例 */}
      <div style={{
        background: 'rgba(13,36,71,0.9)',
        border: '1px solid rgba(59,130,246,0.2)',
        borderRadius: '8px', padding: '8px 12px',
        fontSize: '10px', color: '#94A3B8', fontFamily: 'sans-serif',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#10B981' }} /> 正常
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#F59E0B', marginLeft: 8 }} /> 预警
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#EF4444', marginLeft: 8 }} /> 故障
        </div>
      </div>

      {/* 特写模式信息 */}
      {viewMode === 'detail' && focused && (
        <div style={{
          background: 'rgba(13,36,71,0.9)',
          border: '1px solid rgba(59,130,246,0.4)',
          borderRadius: '8px', padding: '8px 14px',
          fontSize: '12px', color: '#F1F5F9', fontFamily: 'sans-serif',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>🔍 {focused.name}</div>
          <div style={{ fontSize: '10px', color: '#94A3B8' }}>
            HI: {focused.hi_value.toFixed(0)} | 状态: {
              focused.status === 'fault' ? '故障' :
              focused.status === 'warning' ? '预警' : '正常'
            }
          </div>
          <button onClick={() => focusTurbine(null)} style={{
            marginTop: 6,
            background: 'rgba(59,130,246,0.15)',
            border: '1px solid rgba(59,130,246,0.3)',
            borderRadius: '4px', color: '#3B82F6',
            padding: '4px 10px', fontSize: '10px', cursor: 'pointer',
          }}>
            ← 返回总览
          </button>
        </div>
      )}
    </div>
  );
}
