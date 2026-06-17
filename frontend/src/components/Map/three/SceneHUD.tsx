/**
 * SceneHUD — 3D视图叠加控制面板
 * 视角切换 + 图例 + 飞行信息 + 禁飞区开关
 * 参考 AeroMind 控制面板设计
 */

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
  const focused = turbines.find((t) => t.id === focusedTurbineId);

  const [collapsed, setCollapsed] = useState(false);

  const flyingDrones = drones.filter((d) => d.status === 'flying' || d.status === 'returning');

  return (
    <div style={{
      position: 'absolute', top: 12, left: 12, zIndex: 10,
      display: 'flex', flexDirection: 'column', gap: 8, pointerEvents: 'none',
      fontFamily: 'system-ui, sans-serif',
    }}>
      {/* ── 图例 ── */}
      <div style={{
        background: 'rgba(13,36,71,0.9)',
        border: '1px solid rgba(59,130,246,0.2)',
        borderRadius: '8px', padding: '8px 12px',
        fontSize: '10px', color: '#94A3B8',
        pointerEvents: 'auto',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#10B981' }} /> 正常
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#F59E0B', marginLeft: 8 }} /> 预警
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#EF4444', marginLeft: 8 }} /> 故障
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 4 }}>
          <span style={{ width: 10, height: 2, background: '#ef444488', display: 'inline-block' }} />
          <span style={{ color: '#ef4444' }}>禁飞区</span>
        </div>
      </div>

      {/* ── 禁飞区开关 ── */}
      {noFlyZones.length > 0 && (
        <button
          onClick={toggleNoFlyZones}
          style={{
            pointerEvents: 'auto',
            background: showNoFlyZones ? 'rgba(239,68,68,0.15)' : 'rgba(13,36,71,0.8)',
            border: `1px solid ${showNoFlyZones ? 'rgba(239,68,68,0.4)' : 'rgba(75,85,99,0.3)'}`,
            borderRadius: '6px', padding: '6px 10px',
            color: showNoFlyZones ? '#fca5a5' : '#9ca3af',
            fontSize: '10px', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
          }}
        >
          <span>{showNoFlyZones ? '🚫' : '🚫'}</span>
          禁飞区 {showNoFlyZones ? 'ON' : 'OFF'} ({noFlyZones.length})
        </button>
      )}

      {/* ── 特写模式 ── */}
      {viewMode === 'detail' && focused && (
        <div style={{
          background: 'rgba(13,36,71,0.92)',
          border: '1px solid rgba(59,130,246,0.4)',
          borderRadius: '8px', padding: '10px 14px',
          fontSize: '12px', color: '#F1F5F9',
          pointerEvents: 'auto',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>🔍 {focused.name}</div>
          <div style={{ fontSize: '10px', color: '#94A3B8' }}>
            HI: {focused.hi_value.toFixed(0)} | 功率: {focused.power_mw}MW
          </div>
          <div style={{ fontSize: '10px', color: '#94A3B8' }}>
            区域: {focused.region} | 状态: {
              focused.status === 'fault' ? '⚠ 故障' :
              focused.status === 'warning' ? '⚡ 预警' : '✅ 正常'
            }
          </div>
          <button onClick={() => focusTurbine(null)} style={{
            marginTop: 8,
            background: 'rgba(59,130,246,0.15)',
            border: '1px solid rgba(59,130,246,0.3)',
            borderRadius: '4px', color: '#3B82F6',
            padding: '4px 12px', fontSize: '10px', cursor: 'pointer',
          }}>
            ← 返回总览 (Esc)
          </button>
        </div>
      )}

      {/* ── 飞行状态面板 (可折叠) ── */}
      {flyingDrones.length > 0 && (
        <div style={{
          background: 'rgba(13,36,71,0.88)',
          border: '1px solid rgba(59,130,246,0.25)',
          borderRadius: '8px',
          fontSize: '10px', color: '#cbd5e1',
          pointerEvents: 'auto',
          overflow: 'hidden',
        }}>
          <div
            onClick={() => setCollapsed(!collapsed)}
            style={{
              padding: '8px 12px', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              borderBottom: collapsed ? 'none' : '1px solid rgba(59,130,246,0.15)',
            }}
          >
            <span style={{ fontWeight: 600 }}>🚁 机队状态 ({flyingDrones.length})</span>
            <span style={{ color: '#64748b' }}>{collapsed ? '▶' : '▼'}</span>
          </div>

          {!collapsed && (
            <div style={{ padding: '6px 12px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {flyingDrones.map((d) => (
                <div key={d.id} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  borderLeft: `3px solid ${d.color}`, paddingLeft: 8,
                }}>
                  <span style={{ color: d.color, fontWeight: 500, minWidth: 55 }}>{d.name}</span>
                  <span style={{ color: '#94a3b8', fontSize: '9px' }}>
                    📸 {d.completedTurbines.length}/{d.assignedTurbines.length}
                  </span>
                  <span style={{ color: '#94a3b8', fontSize: '9px' }}>🔋 {d.battery.toFixed(0)}%</span>
                  <span style={{
                    fontSize: '8px', padding: '1px 4px', borderRadius: '4px',
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
  );
}
