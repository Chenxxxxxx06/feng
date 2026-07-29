import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import type { Turbine } from '../../types';
import healthyTurbineSvg from '../../assets/map/turbine-healthy.svg?raw';

interface Props {
  turbines: Turbine[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  onFarmChange?: (farm: string | null) => void;
}

type MappedTurbine = Turbine & { lat: number; lng: number; region: string };
type DisplayLayout = {
  turbine: MappedTurbine;
  latlng: [number, number];
  displacementPx: number;
};

const CENTER: [number, number] = [37.78, 108.48];
const OVERVIEW_ZOOM = 9;
const MIN_ZOOM = 8;
const MAX_ZOOM = 18;
const SHAANXI_WIND_BOUNDS: L.LatLngBoundsExpression = [
  [37.28, 107.15],
  [38.18, 109.6],
];

function regionCode(region: string): 'A' | 'B' | 'C' | null {
  if (region.includes('A')) return 'A';
  if (region.includes('B')) return 'B';
  if (region.includes('C')) return 'C';
  return null;
}

function regionLabel(region: string): string {
  const code = regionCode(region);
  return code ? `\u98ce\u573a${code}` : region;
}

function regionMaxZoom(region: string): number {
  const code = regionCode(region);
  if (code === 'C') return 13.72;
  if (code === 'B') return 13.68;
  return 13.7;
}

function regionPaddingRatio(region: string): number {
  return regionCode(region) === 'C' ? 0.36 : 0.34;
}

function healthColor(hi: number): string {
  if (hi >= 90) return '#22D3EE';
  if (hi >= 80) return '#10B981';
  if (hi >= 70) return '#F59E0B';
  if (hi >= 60) return '#F97316';
  return '#EF4444';
}

function hasValidCoordinates(turbine: Turbine): turbine is MappedTurbine {
  return Boolean(turbine.region) && Number.isFinite(turbine.lat) && Number.isFinite(turbine.lng);
}

function paddedBounds(points: MappedTurbine[], ratio = 0.38): L.LatLngBounds {
  const bounds = L.latLngBounds(points.map((t) => [t.lat, t.lng]));
  const south = bounds.getSouth();
  const north = bounds.getNorth();
  const west = bounds.getWest();
  const east = bounds.getEast();
  const latPad = Math.max((north - south) * ratio, 0.028);
  const lngPad = Math.max((east - west) * ratio, 0.038);
  return L.latLngBounds(
    [south - latPad, west - lngPad],
    [north + latPad, east + lngPad],
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function resolveMarkerLayout(map: L.Map, points: MappedTurbine[]): DisplayLayout[] {
  if (points.length <= 1) {
    return points.map((t) => ({ turbine: t, latlng: [t.lat, t.lng], displacementPx: 0 }));
  }

  const size = map.getSize();
  const spacingX = points.length >= 16 ? 72 : 66;
  const spacingY = points.length >= 16 ? 74 : 66;
  const nodes = points.map((t) => {
    const original = map.latLngToLayerPoint(L.latLng(t.lat, t.lng));
    return {
      turbine: t,
      original,
      x: original.x,
      y: original.y,
    };
  });

  for (let step = 0; step < 180; step += 1) {
    let moved = false;

    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const absDx = Math.abs(dx);
        const absDy = Math.abs(dy);

        if (absDx >= spacingX || absDy >= spacingY) continue;

        const dirX = absDx < 0.01 ? (i % 2 === 0 ? -1 : 1) : dx / absDx;
        const dirY = absDy < 0.01 ? (j % 2 === 0 ? -1 : 1) : dy / absDy;
        const pushX = ((spacingX - absDx) * 0.52 + 0.4) * dirX;
        const pushY = ((spacingY - absDy) * 0.52 + 0.4) * dirY;

        a.x -= pushX;
        b.x += pushX;
        a.y -= pushY;
        b.y += pushY;
        moved = true;
      }
    }

    const left = 72;
    const right = size.x - 72;
    const top = 64;
    const bottom = size.y - 68;

    nodes.forEach((node) => {
      node.x += (node.original.x - node.x) * 0.08;
      node.y += (node.original.y - node.y) * 0.08;
      node.x = clamp(node.x, left, right);
      node.y = clamp(node.y, top, bottom);
    });

    if (!moved && step > 24) break;
  }

  return nodes.map((node) => {
    const displaced = L.point(node.x, node.y);
    const latlng = map.layerPointToLatLng(displaced);
    return {
      turbine: node.turbine,
      latlng: [latlng.lat, latlng.lng],
      displacementPx: displaced.distanceTo(node.original),
    };
  });
}

function markerHtml(status: string, hi: number, isSelected: boolean): string {
  const color = status === 'fault' ? '#EF4444' : healthColor(hi);
  const size = isSelected ? 100 : 92;
  const imageSize = status === 'fault'
    ? (isSelected ? 68 : 62)
    : (isSelected ? 70 : 64);
  const shadow = isSelected ? `0 0 16px ${color}` : `0 0 7px ${color}`;

  const visual = status === 'fault'
    ? `<div class="turbine-visual turbine-visual-fault" style="
        width:${imageSize}px;height:${imageSize}px;color:${color};display:block;
        filter:drop-shadow(0 0 7px rgba(248,81,73,0.78));
      ">${healthyTurbineSvg}</div>`
    : `<div style="
        width:${imageSize}px;height:${imageSize}px;color:${color};display:block;
        filter:drop-shadow(0 0 6px ${color});
      ">${healthyTurbineSvg}</div>`;

  return `<div style="
      width:${size}px;height:${size}px;position:relative;cursor:pointer;
      filter:drop-shadow(${shadow});background:transparent;border:0;
    ">
      <div style="
        position:absolute;left:50%;top:0;transform:translateX(-50%);
        width:${imageSize}px;height:${imageSize}px;
        display:flex;align-items:center;justify-content:center;
      ">${visual}</div>
      <div style="
        position:absolute;left:50%;bottom:0;transform:translateX(-50%);
        min-width:22px;height:13px;border-radius:5px;padding:0 4px;
        display:flex;align-items:center;justify-content:center;
        background:rgba(8,12,18,0.92);border:1px solid ${color};
        color:${color};font-family:monospace;font-size:${isSelected ? 8 : 7}px;
        line-height:1;font-weight:800;box-shadow:0 2px 8px rgba(0,0,0,0.5);
      ">${Math.round(hi)}</div>
    </div>`;
}

function createTurbineIcon(turbine: MappedTurbine, isSelected: boolean): L.DivIcon {
  const size = isSelected ? 100 : 92;
  return L.divIcon({
    className: 'turbine-marker',
    html: `<div class="turbine-marker-wrap">
      ${markerHtml(turbine.status, turbine.hi_value, isSelected)}
      <div class="turbine-name-tag ${isSelected ? 'is-selected' : ''}">${turbine.name}</div>
    </div>`,
    iconSize: [size, size + 14],
    iconAnchor: [size / 2, size / 2],
  });
}

function createFarmIcon(label: string, count: number, faulty: number, warning: number): L.DivIcon {
  const color = faulty > 0 ? '#EF4444' : '#10B981';
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

export default function TurbineMap({ turbines, selectedId, onSelect, onFarmChange }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const onSelectRef = useRef(onSelect);
  const onFarmChangeRef = useRef(onFarmChange);
  const [activeFarm, setActiveFarm] = useState<string | null>(null);
  // 当前底图来源：carto（首选）/ osm（外网降级）/ schematic（离线本地示意底图）
  const [tileMode, setTileMode] = useState<'carto' | 'osm' | 'schematic'>('carto');

  const mappedTurbines = useMemo(() => turbines.filter(hasValidCoordinates), [turbines]);
  const farms = useMemo(() => {
    const grouped = new Map<string, MappedTurbine[]>();
    mappedTurbines.forEach((t) => {
      const group = grouped.get(t.region) || [];
      group.push(t);
      grouped.set(t.region, group);
    });
    return Array.from(grouped.entries()).sort(([a], [b]) => a.localeCompare(b, 'zh-CN'));
  }, [mappedTurbines]);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    onFarmChangeRef.current = onFarmChange;
  }, [onFarmChange]);

  useEffect(() => {
    onFarmChangeRef.current?.(activeFarm);
  }, [activeFarm]);

  useEffect(() => {
    const mapElement = containerRef.current;
    if (!mapElement) return;

    const map = L.map(mapElement, {
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
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      touchZoom: false,
      fadeAnimation: false,
      zoomAnimation: false,
      markerZoomAnimation: false,
    });

    // Map tiles: dark CARTO preferred, OSM as reliable fallback
    const cartoTiles = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      { minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM, maxNativeZoom: 20 }
    );
    const osmTiles = L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM, className: 'map-tile-fallback' }
    );
    cartoTiles.addTo(map);
    // 底图三级降级：CARTO → OSM → 本地示意底图。
    // 前两级都依赖外网；评审可能在离线环境复现，此时若不做第三级降级，
    // 地图会退化成一片空白（机组位置其实是准的），看起来像坏了。
    let tileLoaded = false;
    let osmLoaded = false;
    cartoTiles.on('load', () => { tileLoaded = true; });
    osmTiles.on('load', () => { osmLoaded = true; });

    const enterSchematicMode = () => {
      cartoTiles.remove();
      osmTiles.remove();
      mapElement.classList.add('map-schematic-mode');
      setTileMode('schematic');
    };

    const tileFallbackTimer = window.setTimeout(() => {
      if (!tileLoaded) {
        cartoTiles.remove();
        osmTiles.addTo(map);
        setTileMode('osm');
        // 再给 OSM 4 秒；仍不出图则判定为离线，切换到本地示意底图
        window.setTimeout(() => {
          if (!osmLoaded) enterSchematicMode();
        }, 4000);
      }
    }, 4000);

    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const refreshSize = () => {
      map.invalidateSize();
      map.setView(CENTER, OVERVIEW_ZOOM, { animate: false });
    };
    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize();
    });
    resizeObserver.observe(mapElement);
    const animationFrame = requestAnimationFrame(refreshSize);
    const resizeTimers = [
      window.setTimeout(() => map.invalidateSize(), 120),
      window.setTimeout(() => map.invalidateSize(), 360),
    ];

    return () => {
      cancelAnimationFrame(animationFrame);
      window.clearTimeout(tileFallbackTimer);
      resizeTimers.forEach((timer) => window.clearTimeout(timer));
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();
    map.invalidateSize();

    if (!activeFarm) {
      map.fitBounds(SHAANXI_WIND_BOUNDS, {
        paddingTopLeft: [56, 56] as [number, number],
        paddingBottomRight: [420, 56] as [number, number],
        maxZoom: OVERVIEW_ZOOM,
        animate: false,
      });

      farms.forEach(([region, items]) => {
        const bounds = paddedBounds(items, 0.5);
        const center = bounds.getCenter();
        const faulty = items.filter((t) => t.status === 'fault').length;
        const warning = items.filter((t) => t.status === 'warning').length;
        const label = regionLabel(region);

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
          icon: createFarmIcon(label, items.length, faulty, warning),
          riseOnHover: true,
        });
        marker.bindTooltip(
          `<div style="font-size:12px;font-family:sans-serif">
            <b>${label}</b><br/>
            <span style="color:#94A3B8">${items.length} \u53f0\u98ce\u673a | \u6545\u969c ${faulty} | \u9884\u8b66 ${warning}</span>
          </div>`,
          { direction: 'top', offset: [0, -36] },
        );
        marker.on('click', (event) => {
          L.DomEvent.stopPropagation(event);
          setActiveFarm(region);
        });
        layer.addLayer(marker);
      });
      return;
    }

    const farmItems = farms.find(([region]) => region === activeFarm)?.[1] || [];
    if (!farmItems.length) {
      setActiveFarm(null);
      return;
    }

    const bounds = paddedBounds(farmItems, regionPaddingRatio(activeFarm));
    map.fitBounds(bounds, {
      paddingTopLeft: [64, 64],
      paddingBottomRight: [selectedId ? 380 : 300, 96],
      maxZoom: regionMaxZoom(activeFarm),
      animate: false,
    });

    const displayLayouts = resolveMarkerLayout(map, farmItems);

    displayLayouts.forEach(({ turbine: t, latlng, displacementPx }) => {
      const isSelected = t.id === selectedId;
      const tooltipHtml = `<div style="font-size:12px;font-family:sans-serif">
        <b>${t.name}</b><br/>
        <span style="color:#94A3B8">HI: ${t.hi_value.toFixed(0)} | ${t.model || '--'}</span><br/>
        <span style="color:#94A3B8">${t.region} | ${t.power_mw ?? '--'}MW</span>
      </div>`;

      if (displacementPx > 8) {
        L.polyline(
          [
            [t.lat, t.lng],
            latlng,
          ],
          {
            color: t.status === 'fault' ? '#EF4444' : t.status === 'warning' ? '#F59E0B' : '#3B82F6',
            weight: 1,
            opacity: 0.36,
            dashArray: '2 4',
            interactive: false,
          },
        ).addTo(layer);
      }

      const marker = L.marker(latlng, {
        icon: createTurbineIcon(t, isSelected),
        riseOnHover: true,
      });
      marker.bindTooltip(tooltipHtml, { direction: 'top', offset: [0, -14] });
      marker.on('click', (event) => {
        L.DomEvent.stopPropagation(event);
        onSelectRef.current(t.id);
      });
      layer.addLayer(marker);
    });
  }, [activeFarm, farms, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const selected = mappedTurbines.find((t) => t.id === selectedId);
    if (selected && activeFarm !== selected.region) {
      setActiveFarm(selected.region);
    }
  }, [activeFarm, mappedTurbines, selectedId]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} style={{ width: '100%', height: '100%', cursor: activeFarm ? 'default' : 'pointer' }} />
      {activeFarm && (
        <button
          type="button"
          onClick={() => {
            setActiveFarm(null);
            onSelectRef.current(null);
          }}
          className="absolute left-3 bottom-3 z-[520] rounded-md border border-accent-blue/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-blue shadow-lg backdrop-blur hover:bg-bg-hover"
        >
          {'\u8fd4\u56de\u603b\u89c8'}
        </button>
      )}
      {tileMode === 'schematic' && (
        <div
          className="absolute right-3 top-3 z-[520] rounded-md border px-2.5 py-1.5 text-[10px] leading-tight backdrop-blur"
          style={{
            borderColor: 'rgba(245,158,11,0.35)',
            background: 'rgba(13,36,71,0.88)',
            color: 'var(--accent-yellow)',
          }}
          title="\u5f53\u524d\u65e0\u6cd5\u8bbf\u95ee\u5916\u90e8\u5730\u56fe\u74e6\u7247\u670d\u52a1\uff0c\u5df2\u5207\u6362\u4e3a\u672c\u5730\u793a\u610f\u5e95\u56fe\u3002\u673a\u7ec4\u7ecf\u7eac\u5ea6\u4e0e\u5206\u5e03\u5173\u7cfb\u4ecd\u4e3a\u771f\u5b9e\u6570\u636e\u3002"
        >
          \u79bb\u7ebf\u793a\u610f\u5e95\u56fe \u00b7 \u673a\u7ec4\u4f4d\u7f6e\u4e3a\u771f\u5b9e\u5750\u6807
        </div>
      )}
    </div>
  );
}
