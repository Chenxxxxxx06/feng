import { useEffect, useRef } from 'react';
import L from 'leaflet';
import type { Turbine } from '../../types';
import healthyTurbineSvg from '../../assets/map/turbine-healthy.svg?raw';

interface Props {
  turbines: Turbine[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const CENTER: [number, number] = [37.8, 108.4];
const DEFAULT_ZOOM = 9;
const MIN_ZOOM = 4;
const MAX_ZOOM = 18;
const CHINA_BOUNDS: L.LatLngBoundsExpression = [
  [18.0, 73.0],
  [54.0, 135.0],
];

function healthColor(hi: number): string {
  if (hi >= 90) return '#2ee59d';
  if (hi >= 80) return '#3fb950';
  if (hi >= 70) return '#d29922';
  if (hi >= 60) return '#ff9f1c';
  return '#f85149';
}

function markerHtml(status: string, hi: number, isSelected: boolean): string {
  const color = status === 'fault' ? '#f85149' : healthColor(hi);
  const size = isSelected ? 84 : 76;
  const imageSize = isSelected ? 60 : 54;
  const labelWidth = isSelected ? 34 : 30;
  const shadow = isSelected ? `0 0 18px ${color}` : `0 0 8px ${color}`;

  const visual = status === 'fault'
    ? `<img src="/assets/map/turbine-fault.png" alt="" style="
        width:${imageSize}px;height:${imageSize}px;object-fit:contain;display:block;
        filter:drop-shadow(0 0 6px rgba(248,81,73,0.55));
      "/>`
    : `<div style="
        width:${imageSize}px;height:${imageSize}px;color:${color};display:block;
        filter:drop-shadow(0 0 6px ${color});
      ">${healthyTurbineSvg}</div>`;

  return `<div style="
      width:${size}px;height:${size}px;position:relative;
      cursor:pointer;transition:transform 0.18s ease;
      filter:drop-shadow(${shadow});background:transparent;border:0;border-radius:0;
    ">
      <div style="
        position:absolute;left:50%;top:0;transform:translateX(-50%);
        width:${imageSize}px;height:${imageSize}px;
        display:flex;align-items:center;justify-content:center;
      ">
        ${visual}
      </div>
      <div style="
        position:absolute;left:50%;bottom:0;transform:translateX(-50%);
        min-width:${labelWidth}px;height:18px;border-radius:5px;padding:0 5px;
        display:flex;align-items:center;justify-content:center;
        background:rgba(8,12,18,0.9);border:1px solid ${color};
        color:${color};font-family:monospace;font-size:${isSelected ? 11 : 10}px;
        line-height:1;font-weight:800;box-shadow:0 2px 8px rgba(0,0,0,0.5);
      ">${Math.round(hi)}</div>
    </div>`;
}

function createIcon(status: string, hi: number, isSelected: boolean): L.DivIcon {
  const size = isSelected ? 84 : 76;
  return L.divIcon({
    className: 'turbine-marker',
    html: markerHtml(status, hi, isSelected),
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function hasValidCoordinates(turbine: Turbine): turbine is Turbine & { lat: number; lng: number } {
  return Number.isFinite(turbine.lat) && Number.isFinite(turbine.lng);
}

export default function TurbineMap({ turbines, selectedId, onSelect }: Props) {
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const markersByIdRef = useRef<Map<number, L.Marker>>(new Map());
  const hasFitBoundsRef = useRef(false);
  const onSelectRef = useRef(onSelect);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    const map = L.map('turbine-map', {
      center: CENTER,
      zoom: DEFAULT_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      maxBounds: CHINA_BOUNDS,
      maxBoundsViscosity: 0.9,
      worldCopyJump: false,
      zoomControl: true,
      attributionControl: false,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      maxNativeZoom: 20,
      noWrap: true,
      bounds: CHINA_BOUNDS,
      keepBuffer: 8,
      updateWhenIdle: false,
      updateWhenZooming: true,
    }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      markersLayerRef.current = null;
      markersByIdRef.current.clear();
    };
  }, []);

  useEffect(() => {
    const layer = markersLayerRef.current;
    const map = mapRef.current;
    if (!layer || !map) return;

    const mappedTurbines = turbines.filter(hasValidCoordinates);
    const activeIds = new Set(mappedTurbines.map((t) => t.id));

    markersByIdRef.current.forEach((marker, id) => {
      if (!activeIds.has(id)) {
        layer.removeLayer(marker);
        markersByIdRef.current.delete(id);
      }
    });

    mappedTurbines.forEach((t) => {
      const isSelected = t.id === selectedId;
      const tooltipHtml = `<div style="font-size:12px;font-family:sans-serif">
        <b>${t.name}</b><br/>
        <span style="color:#8fa2bc">HI: ${t.hi_value.toFixed(0)} | ${t.model}</span><br/>
        <span style="color:#8fa2bc">${t.region} | ${t.power_mw}MW</span>
      </div>`;

      const existingMarker = markersByIdRef.current.get(t.id);
      if (existingMarker) {
        existingMarker.setLatLng([t.lat, t.lng]);
        existingMarker.setIcon(createIcon(t.status, t.hi_value, isSelected));
        existingMarker.setTooltipContent(tooltipHtml);
        return;
      }

      const marker = L.marker([t.lat, t.lng], {
        icon: createIcon(t.status, t.hi_value, isSelected),
      });
      marker.bindTooltip(tooltipHtml, { direction: 'top', offset: [0, -14] });
      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        onSelectRef.current(t.id);
      });

      layer.addLayer(marker);
      markersByIdRef.current.set(t.id, marker);
    });

    if (!hasFitBoundsRef.current && mappedTurbines.length > 0) {
      const bounds = L.latLngBounds(mappedTurbines.map((t) => [t.lat, t.lng]));
      map.fitBounds(bounds, { padding: [44, 44], maxZoom: DEFAULT_ZOOM });
      hasFitBoundsRef.current = true;
    }
  }, [turbines, selectedId]);

  return <div id="turbine-map" style={{ width: '100%', height: '100%', cursor: 'crosshair' }} />;
}
