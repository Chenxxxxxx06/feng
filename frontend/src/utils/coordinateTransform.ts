/**
 * GPS → 3D 场景米制坐标转换
 * 动态原点：根据 activeFarm 风机的中心自动调整
 * 参考: dronePathPlanner.ts haversine 公式同一数学基础
 */

const METERS_PER_DEG_LAT = 111_320;

function metersPerDegLng(lat: number): number {
  return 111_320 * Math.cos((lat * Math.PI) / 180);
}

let _originLat = 37.78;
let _originLng = 108.48;

let _metersPerDegLngAtOrigin = metersPerDegLng(_originLat);

/** 设置坐标原点（切风场时调用，以该风场中心为原点） */
export function setCoordinateOrigin(lat: number, lng: number): void {
  _originLat = lat;
  _originLng = lng;
  _metersPerDegLngAtOrigin = metersPerDegLng(lat);
}

/** 获取当前原点 */
export function getCoordinateOrigin(): { lat: number; lng: number } {
  return { lat: _originLat, lng: _originLng };
}

/** GPS → Three.js 场景坐标 (x=东, y=上, z=北) */
export function gpsToScene(
  lat: number,
  lng: number,
  elevation = 0,
): [number, number, number] {
  const z = (lat - _originLat) * METERS_PER_DEG_LAT;
  const x = (lng - _originLng) * _metersPerDegLngAtOrigin;
  return [x, elevation, z];
}

/** 计算一组风机的中心点和边界范围 */
export function computeTurbineBounds(
  turbines: { lat: number; lng: number }[],
): { centerLat: number; centerLng: number; extentM: number } | null {
  if (!turbines.length) return null;

  let minLat = Infinity, maxLat = -Infinity;
  let minLng = Infinity, maxLng = -Infinity;

  for (const t of turbines) {
    if (t.lat < minLat) minLat = t.lat;
    if (t.lat > maxLat) maxLat = t.lat;
    if (t.lng < minLng) minLng = t.lng;
    if (t.lng > maxLng) maxLng = t.lng;
  }

  const centerLat = (minLat + maxLat) / 2;
  const centerLng = (minLng + maxLng) / 2;
  const dLat = (maxLat - minLat) * METERS_PER_DEG_LAT;
  const dLng = (maxLng - minLng) * metersPerDegLng(centerLat);
  const extentM = Math.max(dLat, dLng, 800); // 最小 800m

  return { centerLat, centerLng, extentM };
}
