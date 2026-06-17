import { useEffect, useMemo, useRef } from 'react';
import L from 'leaflet';
import type { Turbine, Drone } from '../../types';

interface Props {
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  onFarmSelect: (farm: string | null) => void;
  onTurbineClick?: (turbine: Turbine) => void;
  showPaths: boolean;
  manualMode: boolean;
  selectedDroneId: number | null;
}

type MappedTurbine = Turbine & { lat: number; lng: number; region: string };

const CENTER: [number, number] = [37.78, 108.48];
const OVERVIEW_ZOOM = 9;
const MIN_ZOOM = 8;
const MAX_ZOOM = 18;
const SHAANXI_WIND_BOUNDS: L.LatLngBoundsExpression = [
  [37.28, 107.15],
  [38.18, 109.6],
];

function hasCoords(t: Turbine): t is MappedTurbine {
  return Boolean(t.region) && Number.isFinite(t.lat) && Number.isFinite(t.lng);
}

function paddedBounds(points: MappedTurbine[], ratio = 0.34): L.LatLngBounds {
  const bounds = L.latLngBounds(points.map((t) => [t.lat, t.lng]));
  const latPad = Math.max((bounds.getNorth() - bounds.getSouth()) * ratio, 0.028);
  const lngPad = Math.max((bounds.getEast() - bounds.getWest()) * ratio, 0.038);
  return L.latLngBounds(
    [bounds.getSouth() - latPad, bounds.getWest() - lngPad],
    [bounds.getNorth() + latPad, bounds.getEast() + lngPad],
  );
}

export default function DroneMap({
  turbines, drones, activeFarm, onFarmSelect, onTurbineClick,
  showPaths, manualMode, selectedDroneId,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const staticLayerRef = useRef<L.LayerGroup | null>(null);
  const droneLayerRef = useRef<L.LayerGroup | null>(null);
  const onFarmRef = useRef(onFarmSelect);
  const onTurbineRef = useRef(onTurbineClick);
  onFarmRef.current = onFarmSelect;
  onTurbineRef.current = onTurbineClick;

  const mapped = useMemo(() => turbines.filter(hasCoords), [turbines]);

  const farms = useMemo(() => {
    const g = new Map<string, MappedTurbine[]>();
    mapped.forEach((t) => {
      const arr = g.get(t.region) || [];
      arr.push(t);
      g.set(t.region, arr);
    });
    return Array.from(g.entries()).sort(([a], [b]) => a.localeCompare(b, 'zh-CN'));
  }, [mapped]);

  const completedIds = useMemo(() => {
    const s = new Set<number>();
    drones.forEach((d) => d.completedTurbines.forEach((id) => s.add(id)));
    return s;
  }, [drones]);

  const assignedIds = useMemo(() => {
    const s = new Set<number>();
    drones.forEach((d) => d.assignedTurbines.forEach((id) => s.add(id)));
    return s;
  }, [drones]);

  // Init map (once)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const map = L.map(el, {
      center: CENTER, zoom: OVERVIEW_ZOOM, minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM,
      zoomSnap: 0.25, zoomDelta: 0.25, worldCopyJump: false,
      zoomControl: false, attributionControl: false,
      fadeAnimation: true, zoomAnimation: true, markerZoomAnimation: true,
    });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM, maxNativeZoom: 20,
      noWrap: true, keepBuffer: 16, updateWhenIdle: false, updateWhenZooming: true,
    }).addTo(map);
    staticLayerRef.current = L.layerGroup().addTo(map);
    droneLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el);
    return () => { ro.disconnect(); map.remove(); mapRef.current = null; };
  }, []);

  // Render static: farm zones + turbine markers
  useEffect(() => {
    const map = mapRef.current;
    const layer = staticLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    if (!activeFarm) {
      // ── Overview: show farm rectangles ──
      map.fitBounds(SHAANXI_WIND_BOUNDS, {
        paddingTopLeft: [56, 56], paddingBottomRight: [420, 56],
        maxZoom: OVERVIEW_ZOOM, animate: false,
      });
      farms.forEach(([region, items]) => {
        const bounds = paddedBounds(items, 0.5);
        const center = bounds.getCenter();
        const label = region.includes('A') ? '风场A' : region.includes('B') ? '风场B' : region.includes('C') ? '风场C' : region;

        L.rectangle(bounds, {
          color: '#58a6ff', weight: 1.5, opacity: 0.86, fill: false,
          dashArray: '8 8', interactive: true,
        }).on('click', () => onFarmRef.current(region)).addTo(layer);

        const m = L.marker(center, {
          icon: L.divIcon({
            className: '',
            html: `<div style="width:80px;height:80px;border-radius:50%;border:1.5px dashed #58a6ff;
              background:rgba(88,166,255,0.08);display:flex;flex-direction:column;
              align-items:center;justify-content:center;cursor:pointer;
              filter:drop-shadow(0 0 12px rgba(88,166,255,0.4));">
              <div style="color:#dbeafe;font-size:13px;font-weight:700;">${label}</div>
              <div style="color:#58a6ff;font-size:18px;font-weight:800;margin-top:4px;">${items.length}</div></div>`,
            iconSize: [80, 80], iconAnchor: [40, 40],
          }),
        });
        m.on('click', () => onFarmRef.current(region));
        layer.addLayer(m);
      });
      return;
    }

    // ── Farm detail: show turbines ──
    const farmItems = farms.find(([, items]) => items[0]?.region === activeFarm)?.[1] || [];
    if (!farmItems.length) return;
    const bounds = paddedBounds(farmItems, 0.34);
    map.fitBounds(bounds, {
      paddingTopLeft: [64, 64], paddingBottomRight: [420, 96],
      maxZoom: 14, animate: true, duration: 0.6, easeLinearity: 0.25,
    });

    farmItems.forEach((t) => {
      const shot = completedIds.has(t.id);
      const assigned = assignedIds.has(t.id);
      const borderColor = t.status === 'fault' ? '#f85149' : t.status === 'warning' ? '#d29922' : shot ? '#3fb950' : assigned ? '#388bfd' : '#54657e';
      const size = 160;

      const icon = L.icon({
        iconUrl: '/turbine-marker.png',
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        className: 'drone-turbine-icon',
      });

      const marker = L.marker([t.lat, t.lng], { icon, riseOnHover: true });
      const hiBadge = `<div style="display:inline-block;background:${borderColor};color:#fff;font-size:8px;font-weight:700;border-radius:50%;width:15px;height:15px;text-align:center;line-height:15px;margin-left:4px;border:1px solid rgba(0,0,0,0.4);">${Math.round(t.hi_value)}</div>`;
      marker.bindTooltip(
        `<div style="font-size:11px;font-family:sans-serif"><b>${t.name}</b>${hiBadge}<br/>
        <span style="color:#8fa2bc">HI: ${t.hi_value.toFixed(0)} | ${t.region}</span><br/>
        <span style="color:#8fa2bc">${shot ? '已拍摄' : assigned ? '已分配' : '未分配'}</span></div>`,
        { direction: 'top', offset: [0, -14] },
      );
      marker.on('click', () => onTurbineRef.current?.(t));
      layer.addLayer(marker);
    });
  }, [activeFarm, farms, completedIds, assignedIds]);

  // Render drone paths + animated markers
  useEffect(() => {
    const map = mapRef.current;
    const layer = droneLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    if (!activeFarm || !showPaths) return;

    drones.forEach((drone) => {
      if (drone.path.length < 2) return;
      const latlngs: [number, number][] = drone.path.map((p) => [p.lat, p.lng]);
      const color = drone.color;
      const progressIdx = Math.floor(drone.progress);

      // Completed segment
      if (progressIdx > 0) {
        L.polyline(latlngs.slice(0, progressIdx + 1), {
          color, weight: 2.5, opacity: 0.9,
        }).addTo(layer);
      }
      // Remaining segment
      if (progressIdx < latlngs.length - 1) {
        L.polyline(latlngs.slice(progressIdx), {
          color, weight: 2, opacity: 0.35, dashArray: '6 6',
        }).addTo(layer);
      }
      // Takeoff marker
      if (drone.path.length > 0) {
        const takeoff = drone.path[0];
        L.marker([takeoff.lat, takeoff.lng], {
          icon: L.icon({
            iconUrl: '/takeoff.png',
            iconSize: [140, 140],
            iconAnchor: [70, 140],
            className: '',
          }), zIndexOffset: 500,
        }).bindTooltip(`<div style="font-size:10px"><b>${drone.name} 起飞点</b></div>`, { direction: 'top' }).addTo(layer);
      }

      // Arrows
      const step = Math.max(1, Math.floor(drone.path.length / 8));
      for (let i = 0; i < drone.path.length - 1; i += step) {
        const a = drone.path[i], b = drone.path[i + 1];
        const mid: [number, number] = [(a.lat + b.lat) / 2, (a.lng + b.lng) / 2];
        const angle = (Math.atan2(b.lat - a.lat, b.lng - a.lng) * 180) / Math.PI;
        L.marker(mid, {
          icon: L.divIcon({
            className: '', html: `<div style="transform:rotate(${-angle}deg);color:${color};font-size:40px;opacity:0.6;">▶</div>`,
            iconSize: [50, 50], iconAnchor: [25, 25],
          }), interactive: false,
        }).addTo(layer);
      }
      // Drone position
      if (drone.currentPosition && drone.status === 'flying') {
        const angle = drone.progress > 0 && drone.path.length >= 2
          ? (Math.atan2(
              drone.path[Math.min(Math.floor(drone.progress) + 1, drone.path.length - 1)].lat - drone.currentPosition.lat,
              drone.path[Math.min(Math.floor(drone.progress) + 1, drone.path.length - 1)].lng - drone.currentPosition.lng,
            ) * 180) / Math.PI
          : 0;
        L.marker([drone.currentPosition.lat, drone.currentPosition.lng], {
          icon: L.divIcon({
            className: '',
            html: `<div style="width:210px;height:210px;display:flex;align-items:center;justify-content:center;
              filter:drop-shadow(0 0 14px ${color});transform:rotate(${angle - 90}deg);">
              <img src="/drone.png" width="190" height="190" style="display:block;" />
              <span style="position:absolute;top:-8px;right:-16px;color:#fff;background:${color};
                font-size:11px;font-weight:700;border-radius:50%;width:22px;height:22px;
                display:flex;align-items:center;justify-content:center;border:1px solid rgba(0,0,0,0.4);">${drone.id}</span></div>`,
            iconSize: [210, 210], iconAnchor: [105, 105],
          }), zIndexOffset: 1000,
        }).bindTooltip(
          `<div style="font-size:11px"><b>${drone.name}</b><br/>🔋 ${drone.battery.toFixed(0)}% | 📸 ${drone.completedTurbines.length}/${drone.assignedTurbines.length}</div>`,
          { direction: 'top' },
        ).addTo(layer);
      }
    });
  }, [drones, activeFarm, showPaths]);

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', cursor: activeFarm ? 'default' : 'pointer' }} />
      {activeFarm && (
        <button onClick={() => onFarmRef.current(null)}
          className="absolute left-3 bottom-3 z-[520] rounded-md border border-accent-blue/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-blue shadow-lg backdrop-blur hover:bg-bg-hover">
          返回总览
        </button>
      )}
      {manualMode && activeFarm && (
        <div className="absolute left-3 top-3 z-[520] rounded-md border border-accent-yellow/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-yellow backdrop-blur">
          手动模式：{selectedDroneId ? `点选风机分配给 Drone-${selectedDroneId}` : '先选择一架无人机'}
        </div>
      )}
    </div>
  );
}
