/**
 * 陕北黄土高原程序化地形生成器
 * Simplex Noise 多层叠加 → 丘陵 + 沟壑地貌
 * 参考: three.js 程序化地形经典做法 (vertex displacement + vertexColors)
 */

import { createNoise2D } from 'simplex-noise';

export interface TerrainConfig {
  width: number;
  depth: number;
  segments: number;
  baseAmplitude: number;
  detailAmplitude: number;
  ridgeFactor: number;
  frequencyScale: number;
}

export const DEFAULT_TERRAIN_CONFIG: TerrainConfig = {
  width: 800,
  depth: 800,
  segments: 80,
  baseAmplitude: 35,
  detailAmplitude: 12,
  ridgeFactor: 0.3,
  frequencyScale: 3,
};

const noise2D = createNoise2D();

/** 边缘平滑衰减 (smoothstep 0.7→1.0) */
function edgeFade(ix: number, iz: number, segments: number): number {
  const half = segments / 2;
  const dx = (ix - half) / half;
  const dz = (iz - half) / half;
  const dist = Math.sqrt(dx * dx + dz * dz);
  if (dist <= 0.7) return 1;
  if (dist >= 1) return 0;
  const t = (dist - 0.7) / 0.3;
  return 1 - t * t * (3 - 2 * t);
}

/**
 * 生成地形高度图
 * @returns Float32Array 长度 = (segments+1)², 值域 ~-15~50m
 */
export function generateHeightmap(
  config: Partial<TerrainConfig> = {},
): Float32Array {
  const cfg = { ...DEFAULT_TERRAIN_CONFIG, ...config };
  const { width, depth, segments, baseAmplitude, detailAmplitude, ridgeFactor, frequencyScale } = cfg;
  const count = (segments + 1) * (segments + 1);
  const heights = new Float32Array(count);

  for (let iz = 0; iz <= segments; iz++) {
    for (let ix = 0; ix <= segments; ix++) {
      const worldX = (ix / segments - 0.5) * width;
      const worldZ = (iz / segments - 0.5) * depth;
      const nx = (worldX / width) * frequencyScale;
      const nz = (worldZ / depth) * frequencyScale;

      let h = noise2D(nx, nz) * baseAmplitude;
      h += noise2D(nx * 2.1 + 0.5, nz * 2.1 + 0.5) * detailAmplitude;
      h += Math.abs(noise2D(nx * 1.5 - 0.3, nz * 1.5 - 0.3)) * baseAmplitude * ridgeFactor;

      const fade = edgeFade(ix, iz, segments);
      h *= fade;

      heights[iz * (segments + 1) + ix] = h;
    }
  }
  return heights;
}

/**
 * 采样地形高度 (双线性插值)
 */
export function sampleTerrainHeight(
  x: number,
  z: number,
  heightmap?: Float32Array,
  config?: Partial<TerrainConfig>,
): number {
  const cfg = { ...DEFAULT_TERRAIN_CONFIG, ...config };
  const { width, depth, segments } = cfg;

  const fx = (x / width + 0.5) * segments;
  const fz = (z / depth + 0.5) * segments;

  const ix = Math.floor(fx);
  const iz = Math.floor(fz);

  if (ix < 0 || ix >= segments || iz < 0 || iz >= segments) {
    return 0;
  }

  const hm = heightmap || generateHeightmap(config);
  const tx = fx - ix;
  const tz = fz - iz;

  const h00 = hm[iz * (segments + 1) + ix];
  const h10 = hm[iz * (segments + 1) + ix + 1];
  const h01 = hm[(iz + 1) * (segments + 1) + ix];
  const h11 = hm[(iz + 1) * (segments + 1) + ix + 1];

  const h0 = h00 + (h10 - h00) * tx;
  const h1 = h01 + (h11 - h01) * tx;
  return h0 + (h1 - h0) * tz;
}

/**
 * 高度+坡度 → vertexColor
 */
export function terrainColor(
  height: number,
  slope: number,
): [number, number, number] {
  if (slope > 0.45) return [0.48, 0.55, 0.43]; // 陡坡: 灰绿
  if (height < 5) return [0.55, 0.45, 0.33];     // 低洼: 深黄土
  if (height < 20) return [0.77, 0.64, 0.35];    // 坡面: 典型黄土
  return [0.83, 0.77, 0.55];                       // 高处: 浅黄褐
}
