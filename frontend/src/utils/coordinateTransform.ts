/**
 * GPS → 3D 场景米制坐标转换
 * 原点: 陕北风场区域中心 [37.78, 108.48]
 * 平面近似, 30km 范围内误差 < 3m
 * 参考: dronePathPlanner.ts haversine 公式同一数学基础
 */

const ORIGIN_LAT = 37.78;
const ORIGIN_LNG = 108.48;

const METERS_PER_DEG_LAT = 111_320;
const METERS_PER_DEG_LNG =
  111_320 * Math.cos((ORIGIN_LAT * Math.PI) / 180);

/**
 * GPS 坐标 → Three.js 场景坐标 (右手系: x=东, y=上, z=北)
 */
export function gpsToScene(
  lat: number,
  lng: number,
  elevation = 0,
): [number, number, number] {
  const z = (lat - ORIGIN_LAT) * METERS_PER_DEG_LAT;
  const x = (lng - ORIGIN_LNG) * METERS_PER_DEG_LNG;
  return [x, elevation, z];
}

/**
 * 风机对象 → 场景坐标 (带地面高度)
 */
export function turbineToScenePosition(
  turbine: { lat: number; lng: number },
  groundElevation = 0,
): [number, number, number] {
  return gpsToScene(turbine.lat, turbine.lng, groundElevation);
}

/**
 * 两个 3D 坐标点距离 (米)
 */
export function sceneDistance(
  a: [number, number, number],
  b: [number, number, number],
): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const dz = b[2] - a[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}
