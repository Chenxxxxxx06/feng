import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { Turbine } from '../../types';

interface Props { turbines: Turbine[]; selectedId: number | null; onSelect: (id: number) => void }

const CENTER: [number, number] = [36.6, 109.0];
const DEFAULT_ZOOM = 7;

function statusColor(s: string): string {
  if (s === 'normal') return '#00E676';
  if (s === 'warning') return '#FF9100';
  if (s === 'fault') return '#FF1744';
  return '#445566';
}

function createIcon(status: string, hi: number, isSelected: boolean): L.DivIcon {
  const color = statusColor(status);
  const size = isSelected ? 32 : 20;
  const glow = isSelected ? `0 0 18px ${color}, 0 0 36px ${color}` : `0 0 6px ${color}`;

  return L.divIcon({
    className: 'turbine-marker',
    html: `<div style="
      width:${size}px;height:${size}px;border-radius:50%;
      background:transparent;box-shadow:${glow},inset 0 0 ${size/2}px rgba(0,0,0,0.5);
      border:${isSelected ? '2.5px' : '1.5px'} solid ${color};
      cursor:pointer;display:flex;align-items:center;justify-content:center;
      font-size:${isSelected ? '11px' : '8px'};color:${color};font-weight:600;
      font-family:'Rajdhani','JetBrains Mono',sans-serif;
    ">${Math.round(hi)}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

export default function TurbineMap({ turbines, selectedId, onSelect }: Props) {
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    const map = L.map('turbine-map', {
      center: CENTER, zoom: DEFAULT_ZOOM,
      zoomControl: true, attributionControl: false,
    });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19 }).addTo(map);
    markersLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const layer = markersLayerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;
    layer.clearLayers();

    turbines.forEach((t) => {
      const isSelected = t.id === selectedId;
      const marker = L.marker([t.lat, t.lng], { icon: createIcon(t.status, t.hi_value, isSelected) });
      const statusLabel = t.status === 'normal' ? 'NORMAL' : t.status === 'warning' ? 'WARNING' : 'FAULT';

      marker.bindTooltip(
        `<div style="font-size:12px;font-family:'Inter','PingFang SC',sans-serif;line-height:1.5">
          <b style="color:#E8ECF1">${t.name}</b><br/>
          <span style="color:#8899AA">HI: ${t.hi_value.toFixed(0)} | ${t.model}</span><br/>
          <span style="color:#8899AA">${t.region} | ${t.power_mw}MW | ${statusLabel}</span>
        </div>`,
        { direction: 'top', offset: [0, -16] },
      );

      marker.on('click', (e) => { L.DomEvent.stopPropagation(e); onSelect(t.id); });
      layer.addLayer(marker);
    });

    if (selectedId) {
      const t = turbines.find((x) => x.id === selectedId);
      if (t) map.setView([t.lat, t.lng], 12, { animate: true, duration: 0.5 });
    }
  }, [turbines, selectedId, onSelect]);

  return <div id="turbine-map" style={{ width: '100%', height: '100%', cursor: 'crosshair' }} />;
}
