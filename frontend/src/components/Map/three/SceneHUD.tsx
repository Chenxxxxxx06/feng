import { useState } from 'react';
import { useDrone3DStore } from '../../../services/drone3dStore';

export default function SceneHUD() {
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const noFlyZones = useDrone3DStore((s) => s.noFlyZones);
  const showNoFlyZones = useDrone3DStore((s) => s.showNoFlyZones);
  const toggleNoFlyZones = useDrone3DStore((s) => s.toggleNoFlyZones);
  const cameraMode = useDrone3DStore((s) => s.cameraMode);
  const setCameraMode = useDrone3DStore((s) => s.setCameraMode);
  const selectedDroneId = useDrone3DStore((s) => s.selectedDroneId);
  const setSelectedDroneId = useDrone3DStore((s) => s.setSelectedDroneId);

  const [hidden, setHidden] = useState(false);
  const [flightCollapsed, setFlightCollapsed] = useState(true);
  const focused = turbines.find((t) => t.id === focusedTurbineId);
  const flyingDrones = drones.filter((d) => d.status === 'flying' || d.status === 'returning');
  const selectedDrone = drones.find((d) => d.id === selectedDroneId) ?? drones[0];
  const selectedTakeoff = selectedDrone?.path[0];

  const buttonBase = {
    borderRadius: 6,
    padding: '5px 8px',
    fontSize: 10,
    cursor: 'pointer',
  } as const;

  if (hidden) {
    return (
      <button
        type="button"
        onClick={() => setHidden(false)}
        style={{
          position: 'absolute',
          top: 12,
          left: 12,
          zIndex: 10,
          pointerEvents: 'auto',
          background: 'rgba(13,36,71,0.84)',
          border: '1px solid rgba(96,165,250,0.32)',
          color: '#dbeafe',
          ...buttonBase,
        }}
      >
        显示信息
      </button>
    );
  }

  return (
    <>
    {drones.length > 0 && (
      <div style={{
        position: 'absolute',
        top: 12,
        right: 12,
        zIndex: 11,
        width: 190,
        background: 'rgba(13,36,71,0.9)',
        border: '1px solid rgba(96,165,250,0.3)',
        borderRadius: 8,
        padding: '8px 10px',
        fontSize: 10,
        color: '#cbd5e1',
        pointerEvents: 'auto',
        fontFamily: 'system-ui, sans-serif',
        boxShadow: '0 10px 30px rgba(0,0,0,0.28)',
      }}>
        <label style={{ display: 'block', color: '#94a3b8', marginBottom: 5 }}>起降点</label>
        <select
          value={selectedDroneId ?? drones[0]?.id ?? ''}
          onChange={(event) => setSelectedDroneId(Number(event.target.value))}
          style={{
            width: '100%',
            borderRadius: 6,
            border: '1px solid rgba(96,165,250,0.34)',
            background: 'rgba(15,23,42,0.92)',
            color: '#dbeafe',
            fontSize: 10,
            padding: '5px 7px',
            outline: 'none',
            colorScheme: 'dark',
          }}
        >
          {drones.map((drone) => (
            <option key={drone.id} value={drone.id}>{drone.name} 起降点</option>
          ))}
        </select>
        <div style={{
          marginTop: 7,
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6,
          color: '#94a3b8',
        }}>
          <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 6, padding: '5px 6px', background: 'rgba(15,23,42,0.48)' }}>
            <div>起飞高度</div>
            <div style={{ marginTop: 2, color: '#dbeafe', fontWeight: 600 }}>
              {selectedTakeoff?.alt ? `${selectedTakeoff.alt}m` : '--'}
            </div>
          </div>
          <div style={{ border: '1px solid rgba(148,163,184,0.18)', borderRadius: 6, padding: '5px 6px', background: 'rgba(15,23,42,0.48)' }}>
            <div>巡检高度</div>
            <div style={{ marginTop: 2, color: '#dbeafe', fontWeight: 600 }}>
              {selectedDrone?._altitude ? `${Math.round(selectedDrone._altitude)}m` : '--'}
            </div>
          </div>
        </div>
      </div>
    )}

    <div style={{
      position: 'absolute', top: 12, left: 12, zIndex: 10,
      display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
      fontFamily: 'system-ui, sans-serif', maxWidth: 280,
    }}>
      <div style={{
        background: 'rgba(13,36,71,0.88)',
        border: '1px solid rgba(59,130,246,0.22)',
        borderRadius: 8,
        padding: 6,
        display: 'flex',
        gap: 4,
        pointerEvents: 'auto',
        alignItems: 'center',
      }}>
        {[
          { id: 'overview' as const, label: '总览' },
          { id: 'follow' as const, label: '跟随' },
          { id: 'fpv' as const, label: '无人机视角' },
        ].map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setCameraMode(item.id)}
            style={{
              ...buttonBase,
              border: `1px solid ${cameraMode === item.id ? 'rgba(96,165,250,0.75)' : 'rgba(148,163,184,0.22)'}`,
              background: cameraMode === item.id ? 'rgba(59,130,246,0.22)' : 'rgba(15,23,42,0.58)',
              color: cameraMode === item.id ? '#dbeafe' : '#94a3b8',
            }}
          >
            {item.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setHidden(true)}
          style={{
            ...buttonBase,
            marginLeft: 4,
            border: '1px solid rgba(148,163,184,0.22)',
            background: 'rgba(15,23,42,0.58)',
            color: '#cbd5e1',
          }}
        >
          隐藏
        </button>
      </div>

      <div style={{
        background: 'rgba(13,36,71,0.86)',
        border: '1px solid rgba(59,130,246,0.18)',
        borderRadius: 8,
        padding: '7px 10px',
        fontSize: 10,
        color: '#94a3b8',
        pointerEvents: 'auto',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
          <span style={{ width: 14, height: 2, background: '#facc15' }} /> 拍摄范围
        </div>
        <div style={{ marginTop: 5, color: '#cbd5e1' }}>
          右键拖动原地转向，WASD/方向键移动，Shift 加速，滚轮前进/后退，Q/E 升降。
        </div>
      </div>

      {noFlyZones.length > 0 && (
        <button
          type="button"
          onClick={toggleNoFlyZones}
          style={{
            pointerEvents: 'auto',
            background: showNoFlyZones ? 'rgba(239,68,68,0.15)' : 'rgba(13,36,71,0.8)',
            border: `1px solid ${showNoFlyZones ? 'rgba(239,68,68,0.4)' : 'rgba(75,85,99,0.3)'}`,
            borderRadius: 6, padding: '6px 10px',
            color: showNoFlyZones ? '#fca5a5' : '#9ca3af',
            fontSize: 10, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          禁飞区 {showNoFlyZones ? 'ON' : 'OFF'} ({noFlyZones.length})
        </button>
      )}

      {viewMode === 'detail' && focused && (
        <div style={{
          background: 'rgba(13,36,71,0.9)',
          border: '1px solid rgba(59,130,246,0.36)',
          borderRadius: 8, padding: '10px 12px',
          fontSize: 12, color: '#f1f5f9',
          pointerEvents: 'auto',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{focused.name}</div>
          <div style={{ fontSize: 10, color: '#94a3b8' }}>
            HI: {focused.hi_value.toFixed(0)} | 功率: {focused.power_mw}MW
          </div>
          <div style={{ fontSize: 10, color: '#94a3b8' }}>
            区域: {focused.region} | 状态: {
              focused.status === 'fault' ? '故障' :
              focused.status === 'warning' ? '预警' : '正常'
            }
          </div>
          <button
            type="button"
            onClick={() => focusTurbine(null)}
            style={{
              marginTop: 8,
              background: 'rgba(59,130,246,0.15)',
              border: '1px solid rgba(59,130,246,0.3)',
              borderRadius: 4, color: '#60a5fa',
              padding: '4px 12px', fontSize: 10, cursor: 'pointer',
            }}
          >
            返回总览 (Esc)
          </button>
        </div>
      )}

      {flyingDrones.length > 0 && (
        <div style={{
          background: 'rgba(13,36,71,0.86)',
          border: '1px solid rgba(59,130,246,0.22)',
          borderRadius: 8,
          fontSize: 10, color: '#cbd5e1',
          pointerEvents: 'auto',
          overflow: 'hidden',
        }}>
          <button
            type="button"
            onClick={() => setFlightCollapsed(!flightCollapsed)}
            style={{
              width: '100%',
              padding: '8px 10px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              border: 0,
              borderBottom: flightCollapsed ? 'none' : '1px solid rgba(59,130,246,0.15)',
              background: 'transparent',
              color: '#dbeafe',
              fontSize: 10,
            }}
          >
            <span style={{ fontWeight: 600 }}>机队状态 ({flyingDrones.length})</span>
            <span style={{ color: '#94a3b8' }}>{flightCollapsed ? '展开' : '收起'}</span>
          </button>

          {!flightCollapsed && (
            <div style={{ padding: '6px 10px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {flyingDrones.map((d) => (
                <div key={d.id} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  borderLeft: `3px solid ${d.color}`, paddingLeft: 8,
                }}>
                  <span style={{ color: d.color, fontWeight: 500, minWidth: 55 }}>{d.name}</span>
                  <span style={{ color: '#94a3b8', fontSize: 9 }}>
                    {d.completedTurbines.length}/{d.assignedTurbines.length}
                  </span>
                  <span style={{ color: '#94a3b8', fontSize: 9 }}>{d.battery.toFixed(0)}%</span>
                  <span style={{
                    fontSize: 8, padding: '1px 4px', borderRadius: 4,
                    background: d.status === 'flying' ? 'rgba(59,130,246,0.2)' : 'rgba(34,197,94,0.2)',
                    color: d.status === 'flying' ? '#60a5fa' : '#4ade80',
                  }}>
                    {d.status === 'flying' ? '任务中' : '返航'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
    </>
  );
}
