/**
 * 程序化地形表面 — PlaneGeometry + 噪声顶点位移 + vertexColors
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import {
  generateHeightmap,
  terrainColor,
  DEFAULT_TERRAIN_CONFIG,
} from '../../../utils/terrainGenerator';

export default function TerrainSurface() {
  const geometry = useMemo(() => {
    const cfg = DEFAULT_TERRAIN_CONFIG;
    const { width, depth, segments } = cfg;
    const geo = new THREE.PlaneGeometry(width, depth, segments, segments);
    geo.rotateX(-Math.PI / 2);

    const heights = generateHeightmap();
    const positions = geo.attributes.position;
    const colors = new Float32Array(positions.count * 3);

    // 第一遍: 写入高度
    for (let i = 0; i < positions.count; i++) {
      positions.setY(i, heights[i]);
    }

    // 第二遍: 计算坡度 + vertex color
    for (let iz = 0; iz <= segments; iz++) {
      for (let ix = 0; ix <= segments; ix++) {
        const idx = iz * (segments + 1) + ix;
        const h = positions.getY(idx);

        let slope = 0;
        if (ix > 0 && ix < segments && iz > 0 && iz < segments) {
          const hL = positions.getY(iz * (segments + 1) + (ix - 1));
          const hR = positions.getY(iz * (segments + 1) + (ix + 1));
          const hU = positions.getY((iz - 1) * (segments + 1) + ix);
          const hD = positions.getY((iz + 1) * (segments + 1) + ix);
          const cellSize = width / segments;
          const sx = Math.abs(hR - hL) / (2 * cellSize);
          const sz = Math.abs(hD - hU) / (2 * cellSize);
          slope = Math.sqrt(sx * sx + sz * sz);
        }

        const [r, g, b] = terrainColor(h, slope);
        colors[idx * 3] = r;
        colors[idx * 3 + 1] = g;
        colors[idx * 3 + 2] = b;
      }
    }

    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    return geo;
  }, []);

  return (
    <mesh geometry={geometry} receiveShadow>
      <meshStandardMaterial vertexColors roughness={0.9} metalness={0.05} />
    </mesh>
  );
}
