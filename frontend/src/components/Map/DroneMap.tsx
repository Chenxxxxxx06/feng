import { useEffect, useMemo, useRef } from 'react';
import L from 'leaflet';
import type { Drone, Turbine } from '../../types';
import healthyTurbineSvg from '../../assets/map/turbine-healthy.svg?raw';

interface Props {
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  onFarmSelect: (farm: string | null) => void;
  onTurbineClick?: (turbine: Turbine) => void;
  onMapClick?: (latlng: { lat: number; lng: number }) => void;
  showPaths: boolean;
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

function regionCode(region: string): 'A' | 'B' | 'C' | null {
  if (region.includes('A')) return 'A';
  if (region.includes('B')) return 'B';
  if (region.includes('C')) return 'C';
  return null;
}

function regionLabel(region: string): string {
  const code = regionCode(region);
  return code ? `风场${code}` : region;
}

function regionMaxZoom(region: string): number {
  const code = regionCode(region);
  if (code === 'C') return 14.15;
  if (code === 'B') return 14.05;
  return 14.1;
}

function paddedBounds(points: MappedTurbine[], ratio = 0.28): L.LatLngBounds {
  const bounds = L.latLngBounds(points.map((t) => [t.lat, t.lng]));
  const latPad = Math.max((bounds.getNorth() - bounds.getSouth()) * ratio, 0.018);
  const lngPad = Math.max((bounds.getEast() - bounds.getWest()) * ratio, 0.024);
  return L.latLngBounds(
    [bounds.getSouth() - latPad, bounds.getWest() - lngPad],
    [bounds.getNorth() + latPad, bounds.getEast() + lngPad],
  );
}

function metersPerLng(lat: number): number {
  return 111_320 * Math.cos((lat * Math.PI) / 180);
}

function offsetPoint(point: { lat: number; lng: number }, northM: number, eastM: number) {
  return {
    lat: point.lat + northM / 111_320,
    lng: point.lng + eastM / metersPerLng(point.lat),
  };
}

function colorWithAlpha(color: string, opacity: number): string {
  return `${color}${Math.round(opacity * 255).toString(16).padStart(2, '0')}`;
}

function markerHtml(routeColor: string | null, isSelected: boolean, isCompleted: boolean): string {
  const color = routeColor || '#94A3B8';
  const size = isSelected ? 92 : 84;
  const imageSize = isSelected ? 64 : 58;
  const opacity = routeColor ? 1 : 0.56;
  const halo = isCompleted ? 16 : isSelected ? 14 : 8;
  return `<div style="width:${size}px;height:${size}px;position:relative;cursor:pointer;opacity:${opacity};filter:drop-shadow(0 0 ${halo}px ${colorWithAlpha(color, routeColor ? 0.78 : 0.35)});">
    <div style="position:absolute;left:50%;top:0;transform:translateX(-50%);width:${imageSize}px;height:${imageSize}px;color:${color};display:flex;align-items:center;justify-content:center;">
      ${healthyTurbineSvg}
    </div>
    <div style="position:absolute;left:50%;bottom:3px;transform:translateX(-50%);width:22px;height:4px;border-radius:999px;background:${color};box-shadow:0 0 10px ${colorWithAlpha(color, 0.82)};"></div>
  </div>`;
}

function createTurbineIcon(turbine: MappedTurbine, selected: boolean, routeColor: string | null, completed: boolean): L.DivIcon {
  const size = selected ? 92 : 84;
  return L.divIcon({
    className: 'turbine-marker',
    html: `<div class="turbine-marker-wrap">
      ${markerHtml(routeColor, selected, completed)}
      <div class="turbine-name-tag ${selected ? 'is-selected' : ''}">${turbine.name}</div>
    </div>`,
    iconSize: [size, size + 14],
    iconAnchor: [size / 2, size / 2],
  });
}

function createFarmIcon(label: string, count: number, faulty: number, warning: number): L.DivIcon {
  const color = faulty > 0 ? '#EF4444' : warning > 0 ? '#F59E0B' : '#10B981';
  const tone = faulty > 0 ? 'fault' : warning > 0 ? 'warning' : 'healthy';
  return L.divIcon({
    className: 'farm-marker',
    html: `<div class="farm-marker-shell farm-marker-${tone}" style="--farm-color:${color}">
      <div class="farm-marker-ring"></div>
      <div class="farm-marker-core">
        <div class="farm-marker-title">${label}</div>
        <div class="farm-marker-count">${count}</div>
      </div>
    </div>`,
    iconSize: [98, 98],
    iconAnchor: [49, 49],
  });
}

function createDroneIcon(drone: Drone, angle: number): L.DivIcon {
  return L.divIcon({
    className: '',
    html: `<div style="width:38px;height:38px;display:flex;align-items:center;justify-content:center;filter:drop-shadow(0 0 12px ${drone.color});transform:rotate(${angle - 90}deg);">
      <img src="/drone.png" width="32" height="32" style="display:block;" />
      <span style="position:absolute;top:-4px;right:-8px;color:#fff;background:${drone.color};font-size:8px;font-weight:800;border-radius:50%;width:15px;height:15px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(0,0,0,0.45);">${drone.id}</span>
    </div>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });
}

function createTakeoffIcon(drone: Drone): L.DivIcon {
  return L.divIcon({
    className: '',
    html: `<div style="width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(8,18,34,0.94);border:2px solid ${drone.color};box-shadow:0 0 16px ${drone.color}66;color:${drone.color};font-size:20px;font-weight:900;">↥</div>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19],
  });
}

export default function DroneMap({
  turbines,
  drones,
  activeFarm,
  onFarmSelect,
  onTurbineClick,
  onMapClick,
  showPaths,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const turbineLayerRef = useRef<L.LayerGroup | null>(null);
  const droneLayerRef = useRef<L.LayerGroup | null>(null);
  const onFarmRef = useRef(onFarmSelect);
  const onTurbineRef = useRef(onTurbineClick);
  const onMapRef = useRef(onMapClick);
  onFarmRef.current = onFarmSelect;
  onTurbineRef.current = onTurbineClick;
  onMapRef.current = onMapClick;

  const mapped = useMemo(() => turbines.filter(hasCoords), [turbines]);
  const farms = useMemo(() => {
    const grouped = new Map<string, MappedTurbine[]>();
    mapped.forEach((t) => {
      const items = grouped.get(t.region) || [];
      items.push(t);
      grouped.set(t.region, items);
    });
    return Array.from(grouped.entries()).sort(([a], [b]) => a.localeCompare(b, 'zh-CN'));
  }, [mapped]);

  const assignedIds = useMemo(() => {
    const ids = new Set<number>();
    drones.forEach((d) => d.assignedTurbines.forEach((id) => ids.add(id)));
    return ids;
  }, [drones]);

  const completedIds = useMemo(() => {
    const ids = new Set<number>();
    drones.forEach((d) => d.completedTurbines.forEach((id) => ids.add(id)));
    return ids;
  }, [drones]);

  const turbineRouteColors = useMemo(() => {
    const colors = new Map<number, string>();
    drones.forEach((drone) => {
      drone.assignedTurbines.forEach((id) => colors.set(id, drone.color));
    });
    return colors;
  }, [drones]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const map = L.map(el, {
      center: CENTER,
      zoom: OVERVIEW_ZOOM,
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      zoomSnap: 0.25,
      zoomDelta: 0.25,
      worldCopyJump: false,
      zoomControl: false,
      attributionControl: false,
      dragging: true,
      scrollWheelZoom: true,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: true,
      fadeAnimation: false,
      zoomAnimation: false,
      markerZoomAnimation: false,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      maxNativeZoom: 20,
      noWrap: true,
      keepBuffer: 8,
      updateWhenIdle: true,
      updateWhenZooming: false,
    }).addTo(map);

    turbineLayerRef.current = L.layerGroup().addTo(map);
    droneLayerRef.current = L.layerGroup().addTo(map);
    map.on('click', (e: L.LeafletMouseEvent) => onMapRef.current?.({ lat: e.latlng.lat, lng: e.latlng.lng }));
    mapRef.current = map;

    const resizeObserver = new ResizeObserver(() => map.invalidateSize());
    resizeObserver.observe(el);
    requestAnimationFrame(() => map.invalidateSize());
    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Fit bounds only when farm changes — NOT on every drone tick
  const prevFarmRef = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.invalidateSize();

    if (!activeFarm) {
      if (prevFarmRef.current !== null) {
        map.fitBounds(SHAANXI_WIND_BOUNDS, {
          paddingTopLeft: [56, 56],
          paddingBottomRight: [360, 56],
          maxZoom: OVERVIEW_ZOOM,
          animate: false,
        });
      }
      prevFarmRef.current = null;
      return;
    }

    const farmItems = farms.find(([region]) => region === activeFarm)?.[1] || [];
    if (!farmItems.length) return;

    if (prevFarmRef.current !== activeFarm) {
      map.fitBounds(paddedBounds(farmItems, 0.22), {
        paddingTopLeft: [42, 42],
        paddingBottomRight: [42, 42],
        maxZoom: regionMaxZoom(activeFarm),
        animate: false,
      });
    }
    prevFarmRef.current = activeFarm;
  }, [activeFarm, farms]);

  // Render turbine markers — updates when route colors change
  useEffect(() => {
    const map = mapRef.current;
    const layer = turbineLayerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    map.invalidateSize();

    if (!activeFarm) {
      farms.forEach(([region, items]) => {
        const bounds = paddedBounds(items, 0.5);
        const center = bounds.getCenter();
        const faulty = items.filter((t) => t.status === 'fault').length;
        const warning = items.filter((t) => t.status === 'warning').length;

        L.rectangle(bounds, {
          color: '#3B82F6',
          weight: 1.5,
          opacity: 0.86,
          fill: false,
          dashArray: '8 8',
          interactive: false,
          className: 'farm-range-outline',
        }).addTo(layer);

        const marker = L.marker(center, {
          icon: createFarmIcon(regionLabel(region), items.length, faulty, warning),
          riseOnHover: true,
        });
        marker.bindTooltip(
          `<div style="font-size:12px;font-family:sans-serif"><b>${regionLabel(region)}</b><br/><span style="color:#94A3B8">${items.length} 台风机 | 故障 ${faulty} | 预警 ${warning}</span></div>`,
          { direction: 'top', offset: [0, -36] },
        );
        marker.on('click', (event) => {
          L.DomEvent.stopPropagation(event);
          onFarmRef.current(region);
        });
        layer.addLayer(marker);
      });
      return;
    }

    const farmItems = farms.find(([region]) => region === activeFarm)?.[1] || [];
    if (!farmItems.length) return;

    farmItems.forEach((t) => {
      const routeColor = turbineRouteColors.get(t.id) || null;
      const marker = L.marker([t.lat, t.lng], {
        icon: createTurbineIcon(t, false, routeColor, completedIds.has(t.id)),
        riseOnHover: true,
      });
      marker.bindTooltip(
        `<div style="font-size:12px;font-family:sans-serif"><b>${t.name}</b><br/><span style="color:#94A3B8">${routeColor ? `所属线路 <span style="color:${routeColor};font-weight:700">●</span>` : '未分配线路'} | ${completedIds.has(t.id) ? '已拍摄' : assignedIds.has(t.id) ? '待拍摄' : '待分配'}</span><br/><span style="color:#94A3B8">${t.model || '--'}</span></div>`,
        { direction: 'top', offset: [0, -14] },
      );
      marker.on('click', (event) => {
        L.DomEvent.stopPropagation(event);
        onTurbineRef.current?.(t);
      });
      layer.addLayer(marker);
    });
  }, [activeFarm, farms, assignedIds, completedIds, turbineRouteColors]);

  useEffect(() => {
    const layer = droneLayerRef.current;
    if (!layer) return;
    layer.clearLayers();
    if (!activeFarm || !showPaths) return;

    drones.forEach((drone) => {
      if (drone.path.length < 2) return;
      const latlngs: [number, number][] = drone.path.map((p) => [p.lat, p.lng]);
      const progressIdx = Math.min(Math.floor(drone.progress), latlngs.length - 1);

      if (progressIdx > 0) {
        L.polyline(latlngs.slice(0, progressIdx + 1), { color: drone.color, weight: 7, opacity: 0.16 }).addTo(layer);
        L.polyline(latlngs.slice(0, progressIdx + 1), { color: drone.color, weight: 3.4, opacity: 0.95 }).addTo(layer);
      }

      if (progressIdx < latlngs.length - 1) {
        L.polyline(latlngs.slice(progressIdx), {
          color: drone.color,
          weight: 2.6,
          opacity: 0.56,
          dashArray: '12 10',
          className: 'drone-path-remaining',
        }).addTo(layer);
      }

      const takeoff = drone.path[0] ?? null;
      if (!takeoff) return;
      const realStart = drone.path.find((p) => p.kind === 'inspect') ?? drone.path[1];
      if (realStart) {
        L.polyline([[takeoff.lat, takeoff.lng], [realStart.lat, realStart.lng]], {
          color: drone.color,
          weight: 1.4,
          opacity: 0.52,
          dashArray: '4 5',
          interactive: false,
        }).addTo(layer);
      }

      L.marker([takeoff.lat, takeoff.lng], {
        icon: createTakeoffIcon(drone),
        zIndexOffset: 620,
      }).bindTooltip(`<div style="font-size:11px"><b>${drone.name} 起降点</b></div>`, { direction: 'top' }).addTo(layer);

      const step = Math.max(1, Math.floor(drone.path.length / 8));
      for (let i = 0; i < drone.path.length - 1; i += step) {
        const a = drone.path[i];
        const b = drone.path[i + 1];
        const mid: [number, number] = [(a.lat + b.lat) / 2, (a.lng + b.lng) / 2];
        const angle = (Math.atan2(b.lat - a.lat, b.lng - a.lng) * 180) / Math.PI;
        L.marker(mid, {
          icon: L.divIcon({
            className: '',
            html: `<div style="transform:rotate(${-angle}deg);color:${drone.color};font-size:11px;opacity:0.78;">▶</div>`,
            iconSize: [12, 12],
            iconAnchor: [6, 6],
          }),
          interactive: false,
        }).addTo(layer);
      }

      if (drone.currentPosition && (drone.status === 'flying' || drone.status === 'returning')) {
        const next = drone.path[Math.min(progressIdx + 1, drone.path.length - 1)] ?? drone.currentPosition;
        const angle = (Math.atan2(next.lat - drone.currentPosition.lat, next.lng - drone.currentPosition.lng) * 180) / Math.PI;
        L.marker([drone.currentPosition.lat, drone.currentPosition.lng], {
          icon: createDroneIcon(drone, angle),
          zIndexOffset: 1000,
        }).bindTooltip(
          `<div style="font-size:11px"><b>${drone.name}</b><br/>电量 ${drone.battery.toFixed(0)}% | 拍摄 ${drone.completedTurbines.length}/${drone.assignedTurbines.length}</div>`,
          { direction: 'top' },
        ).addTo(layer);
      }
    });
  }, [activeFarm, drones, showPaths]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} style={{ width: '100%', height: '100%', cursor: activeFarm ? 'default' : 'pointer' }} />
      {activeFarm && (
        <button
          type="button"
          onClick={() => onFarmRef.current(null)}
          className="absolute left-3 bottom-3 z-[520] rounded-md border border-accent-blue/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-blue shadow-lg backdrop-blur hover:bg-bg-hover"
        >
          返回总览
        </button>
      )}
    </div>
  );
}
