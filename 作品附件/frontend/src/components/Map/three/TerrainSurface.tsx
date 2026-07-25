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

function createTerrainTexture(): THREE.CanvasTexture {
  const tileSize = 1024;
  const canvas = document.createElement('canvas');
  canvas.width = tileSize;
  canvas.height = tileSize;
  const ctx = canvas.getContext('2d');
  if (!ctx) return new THREE.CanvasTexture(canvas);

  ctx.fillStyle = '#425842';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const image = ctx.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const nx = x / canvas.width;
      const ny = y / canvas.height;
      const broad = Math.sin(nx * 15.3 + ny * 6.5) * 0.5 + 0.5;
      const field = Math.sin(nx * 42.0 - ny * 21.0) * Math.cos(nx * 13.5 + ny * 31.0);
      const grain = Math.sin((x * 12.9898 + y * 78.233) * 0.018) * 0.5 + 0.5;
      const ridge = Math.max(0, Math.min(1, broad * 0.45 + field * 0.2 + grain * 0.35));
      const meadow = Math.max(0, Math.min(1, Math.sin(nx * 8.0 - ny * 5.5) * 0.5 + 0.5));
      const i = (y * canvas.width + x) * 4;
      image.data[i] = 42 + ridge * 58 + meadow * 12;
      image.data[i + 1] = 58 + ridge * 70 + meadow * 22;
      image.data[i + 2] = 43 + ridge * 45 + meadow * 8;
      image.data[i + 3] = 255;
    }
  }
  ctx.putImageData(image, 0, 0);

  ctx.globalAlpha = 0.18;
  for (let i = 0; i < 18; i += 1) {
    const x = (i * 97) % canvas.width;
    const y = (i * 173) % canvas.height;
    const w = 110 + ((i * 41) % 170);
    const h = 46 + ((i * 23) % 90);
    ctx.fillStyle = i % 3 === 0 ? '#7b8455' : i % 3 === 1 ? '#536b47' : '#6a714c';
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(((i % 7) - 3) * 0.18);
    ctx.fillRect(-w / 2, -h / 2, w, h);
    ctx.restore();
  }
  ctx.globalAlpha = 1;

  ctx.strokeStyle = 'rgba(214,204,158,0.35)';
  ctx.lineWidth = 2;
  for (let i = 0; i < 6; i += 1) {
    ctx.beginPath();
    const y = canvas.height * (0.12 + i * 0.15);
    ctx.moveTo(0, y);
    ctx.bezierCurveTo(
      canvas.width * 0.24,
      y - 65 + i * 7,
      canvas.width * 0.62,
      y + 82 - i * 9,
      canvas.width,
      y + 8,
    );
    ctx.stroke();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1.5, 1.5);
  texture.anisotropy = 16;
  texture.generateMipmaps = true;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;

  return texture;
}

function ServiceRoads({ width, depth }: Props) {
  const roadLines = useMemo(() => {
    const curves = [
      [[-0.42, 0.18], [-0.18, 0.04], [0.08, -0.02], [0.38, -0.2]],
      [[-0.36, -0.28], [-0.12, -0.18], [0.18, 0.1], [0.4, 0.24]],
      [[-0.18, 0.34], [0.02, 0.16], [0.25, 0.1], [0.46, 0.0]],
    ];
    return curves.map((curve) => {
      const points = curve.map(([x, z]) => new THREE.Vector3(x * width, 2.2, z * depth));
      return new THREE.CatmullRomCurve3(points).getPoints(64);
    });
  }, [width, depth]);

  return (
    <group>
      {roadLines.map((points, index) => (
        <group key={index}>
          <line>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                count={points.length}
                array={new Float32Array(points.flatMap((p) => [p.x, p.y, p.z]))}
                itemSize={3}
              />
            </bufferGeometry>
            <lineBasicMaterial color="#2f2d25" transparent opacity={0.42} />
          </line>
          <line>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                count={points.length}
                array={new Float32Array(points.flatMap((p) => [p.x, p.y + 0.12, p.z]))}
                itemSize={3}
              />
            </bufferGeometry>
            <lineBasicMaterial color="#d5c082" transparent opacity={0.36} />
          </line>
        </group>
      ))}
    </group>
  );
}

function FarmBoundary({ width, depth }: Props) {
  return (
    <group position={[0, 2.8, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.min(width, depth) * 0.32, Math.min(width, depth) * 0.325, 96]} />
        <meshBasicMaterial color="#58a6ff" transparent opacity={0.16} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.min(width, depth) * 0.46, Math.min(width, depth) * 0.462, 120]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.08} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
    </group>
  );
}

export default function TerrainSurface({ width, depth, segments = 150 }: Props) {
  const texture = useMemo(() => createTerrainTexture(), []);

  const geometry = useMemo(() => {
    const actualSeg = Math.max(96, Math.min(segments, 190));
    const geo = new THREE.PlaneGeometry(width, depth, actualSeg, actualSeg);
    geo.rotateX(-Math.PI / 2);

    const heights = generateHeightmap({
      width,
      depth,
      segments: actualSeg,
      baseAmplitude: 22,
      detailAmplitude: 9,
      ridgeFactor: 0.2,
      frequencyScale: 2.4,
    });
    const positions = geo.attributes.position;
    const colors = new Float32Array(positions.count * 3);

    for (let i = 0; i < positions.count; i += 1) {
      positions.setY(i, heights[i]);
    }

    for (let iz = 0; iz <= actualSeg; iz += 1) {
      for (let ix = 0; ix <= actualSeg; ix += 1) {
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
    <group>
      <mesh geometry={geometry} receiveShadow>
        <meshStandardMaterial
          map={texture}
          vertexColors
          roughness={0.86}
          metalness={0.02}
          color="#ffffff"
        />
      </mesh>
      <ServiceRoads width={width} depth={depth} segments={segments} />
      <FarmBoundary width={width} depth={depth} segments={segments} />
    </group>
  );
}
