/**
 * 程序化地形表面 — 动态尺寸, Simplex 噪声顶点位移 + vertexColors
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import {
  generateHeightmap,
  terrainColor,
} from '../../../utils/terrainGenerator';

interface Props {
  width: number;
  depth: number;
  segments?: number;
}

export default function TerrainSurface({ width, depth, segments = 80 }: Props) {
  const geometry = useMemo(() => {
    const seg = Math.min(segments, Math.floor(Math.sqrt(width * depth) / 5));
    const actualSeg = Math.max(40, Math.min(seg, 120));
    const geo = new THREE.PlaneGeometry(width, depth, actualSeg, actualSeg);
    geo.rotateX(-Math.PI / 2);

    const heights = generateHeightmap({ width, depth, segments: actualSeg });
    const positions = geo.attributes.position;
    const colors = new Float32Array(positions.count * 3);

    for (let i = 0; i < positions.count; i++) {
      positions.setY(i, heights[i]);
    }

    for (let iz = 0; iz <= actualSeg; iz++) {
      for (let ix = 0; ix <= actualSeg; ix++) {
        const idx = iz * (actualSeg + 1) + ix;
        const h = positions.getY(idx);
        let slope = 0;
        if (ix > 0 && ix < actualSeg && iz > 0 && iz < actualSeg) {
          const hl = positions.getY(iz * (actualSeg + 1) + (ix - 1));
          const hr = positions.getY(iz * (actualSeg + 1) + (ix + 1));
          const hu = positions.getY((iz - 1) * (actualSeg + 1) + ix);
          const hd = positions.getY((iz + 1) * (actualSeg + 1) + ix);
          const cs = width / actualSeg;
          slope = Math.sqrt(((hr - hl) ** 2 + (hd - hu) ** 2)) / (2 * cs);
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
  }, [width, depth, segments]);

  return (
    <mesh geometry={geometry} receiveShadow>
      <meshStandardMaterial vertexColors roughness={0.9} metalness={0.05} />
    </mesh>
  );
}
