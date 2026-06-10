import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { Turbine } from '../../types';

interface Props {
  turbines: Turbine[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const CENTER: [number, number] = [36.6, 109.0];
const DEFAULT_ZOOM = 7;

function statusColor(status: string): string {
  switch (status) {
    case 'normal': return '#3fb950';
    case 'warning': return '#d29922';
    case 'fault': return '#f85149';
    default: return '#54657e';
  }
}

function createIcon(status: string, hi: number, isSelected: boolean): L.DivIcon {
  const color = statusColor(status);
  const size = isSelected ? 28 : 20;
  const glow = isSelected ? `0 0 16px ${color}, 0 0 32px ${color}` : `0 0 6px ${color}`;
  return L.divIcon({
    className: 'turbine-marker',
    html: `<div style="
      width:${size}px;height:${size}px;border-radius:50%;
      background:${color};box-shadow:${glow};
      border:2px solid rgba(255,255,255,0.8);
      cursor:pointer;display:flex;align-items:center;justify-content:center;
      font-size:${isSelected ? 10 : 8}px;color:#fff;font-weight:bold;
      transition:all 0.2s ease;
      font-family:monospace;
    ">${Math.round(hi)}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

export default function TurbineMap({ turbines, selectedId, onSelect }: Props) {
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);

  // Init map once
  useEffect(() => {
    const map = L.map('turbine-map', {
      center: CENTER,
      zoom: DEFAULT_ZOOM,
      zoomControl: true,
      attributionControl: false,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
    }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Update markers whenever turbines or selectedId changes
  useEffect(() => {
    const layer = markersLayerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;

    layer.clearLayers();

    turbines.forEach((t) => {
      const isSelected = t.id === selectedId;
      const marker = L.marker([t.lat, t.lng], {
        icon: createIcon(t.status, t.hi_value, isSelected),
      });

      marker.bindTooltip(
        `<div style="font-size:12px;font-family:sans-serif">
          <b>${t.name}</b><br/>
          <span style="color:#8fa2bc">HI: ${t.hi_value.toFixed(0)} | ${t.model}</span><br/>
          <span style="color:#8fa2bc">${t.region} | ${t.power_mw}MW</span>
        </div>`,
        { direction: 'top', offset: [0, -14] },
      );

      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        onSelect(t.id);
      });

      layer.addLayer(marker);
    });

    // Pan to selected
    if (selectedId) {
      const t = turbines.find((x) => x.id === selectedId);
      if (t) {
        map.setView([t.lat, t.lng], 12, { animate: true, duration: 0.5 });
      }
    }
  }, [turbines, selectedId, onSelect]);

  return <div id="turbine-map" style={{ width: '100%', height: '100%', cursor: 'crosshair' }} />;
}
