# 3D 风场数字孪生 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DroneSchedulerPage 右侧新增 Three.js 3D 辅助视图，程序化地形 + GLTF 风机/无人机模型 + 实时数据同步

**Architecture:** react-three-fiber + drei 声明式 3D 组件，共享 zustand store 与现有 2D Leaflet 同步数据，左右分屏布局。仅修改 1 个现有文件（DroneSchedulerPage.tsx），其他全部新建。

**Tech Stack:** React 18 + TypeScript 5.6 + @react-three/fiber 8.x + @react-three/drei 9.x + three 0.170 + simplex-noise 4.x + zustand 5.x

---

## File Structure

```
frontend/src/
├── components/Map/three/        # 🆕 10 files
│   ├── WindFarm3DView.tsx
│   ├── OverviewScene.tsx
│   ├── DetailScene.tsx
│   ├── TerrainSurface.tsx
│   ├── TurbineInstance.tsx
│   ├── DroneInstance.tsx
│   ├── FlightPathLines.tsx
│   ├── BladeHighlights.tsx
│   ├── EnvironmentSetup.tsx
│   └── CameraManager.tsx
├── services/
│   └── drone3dStore.ts          # 🆕
├── utils/
│   ├── coordinateTransform.ts   # 🆕
│   └── terrainGenerator.ts      # 🆕
├── pages/DroneScheduler/
│   └── DroneSchedulerPage.tsx   # 修改
├── public/models/               # 🆕 目录
│   ├── wind-turbine.glb         # 🆕 (用户下载)
│   └── drone-quadcopter.glb     # 🆕 (用户下载)
└── package.json                 # 修改 (+3 deps)
```

---

## Phase 1: 基础骨架 (Foundation)

### Task 1: Install Dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install npm packages**

```bash
cd frontend && npm install @react-three/fiber @react-three/drei three simplex-noise
```

- [ ] **Step 2: Install TypeScript types**

```bash
cd frontend && npm install -D @types/three
```

- [ ] **Step 3: Verify installation**

```bash
cd frontend && node -e "require('three'); console.log('three OK')" && node -e "require('simplex-noise'); console.log('simplex-noise OK')"
```

Expected: prints "three OK" and "simplex-noise OK"

- [ ] **Step 4: Create models directory**

```bash
mkdir -p frontend/public/models
```

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add @react-three/fiber @react-three/drei three simplex-noise

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create GPS → 3D Coordinate Transform

**Files:**
- Create: `frontend/src/utils/coordinateTransform.ts`

- [ ] **Step 1: Write coordinateTransform.ts**

```typescript
/**
 * GPS → 3D 场景米制坐标转换
 * 原点: 陕北风场区域中心 [37.78, 108.48]
 * 平面近似, 30km 范围内误差 < 3m
 */

const ORIGIN_LAT = 37.78;
const ORIGIN_LNG = 108.48;

const METERS_PER_DEG_LAT = 111_320;
const METERS_PER_DEG_LNG =
  111_320 * Math.cos((ORIGIN_LAT * Math.PI) / 180);

/**
 * 将 GPS 坐标转换为 Three.js 场景坐标
 * @returns [x, y, z] — Three.js 坐标系 (x=东, y=上, z=北)
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
 * 从风机 Turbine 对象直接获取场景坐标
 */
export function turbineToScenePosition(
  turbine: { lat: number; lng: number },
  groundElevation = 0,
): [number, number, number] {
  return gpsToScene(turbine.lat, turbine.lng, groundElevation);
}

/**
 * 计算两点间的场景距离 (米)
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
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/utils/coordinateTransform.ts
git commit -m "feat: add GPS to 3D scene coordinate transform utility

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Create Terrain Heightmap Generator

**Files:**
- Create: `frontend/src/utils/terrainGenerator.ts`

- [ ] **Step 1: Write terrainGenerator.ts**

```typescript
/**
 * 陕北黄土高原程序化地形生成器
 * 使用 Simplex Noise 多层叠加模拟丘陵+沟壑地貌
 */

import { createNoise2D } from 'simplex-noise';

/** 地形配置 */
export interface TerrainConfig {
  /** 平面宽度 (米) */
  width: number;
  /** 平面深度 (米) */
  depth: number;
  /** 每边顶点数 (总顶点数 = segments+1 的平方) */
  segments: number;
  /** 基础起伏振幅 (米) */
  baseAmplitude: number;
  /** 细节层振幅 (米) */
  detailAmplitude: number;
  /** 山脊因子 (0-1) */
  ridgeFactor: number;
  /** 噪声频率缩放 */
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

/** 创建 2D Simplex 噪声函数 (使用固定种子确保可重现) */
const noise2D = createNoise2D();

/** 边缘平滑衰减函数 */
function edgeFade(ix: number, iz: number, segments: number): number {
  const half = segments / 2;
  const dx = (ix - half) / half;
  const dz = (iz - half) / half;
  const dist = Math.sqrt(dx * dx + dz * dz);
  if (dist <= 0.7) return 1;
  if (dist >= 1) return 0;
  // smoothstep: 0.7→1.0 range
  const t = (dist - 0.7) / 0.3;
  return 1 - t * t * (3 - 2 * t);
}

/**
 * 生成地形高度图
 * @returns Float32Array 长度 = (segments+1)², 值范围约 -15~50 米
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

      // 多层噪声叠加
      let h = noise2D(nx, nz) * baseAmplitude;
      h += noise2D(nx * 2.1 + 0.5, nz * 2.1 + 0.5) * detailAmplitude;
      // 山脊 (取绝对值产生沟壑效果)
      h += Math.abs(noise2D(nx * 1.5 - 0.3, nz * 1.5 - 0.3)) * baseAmplitude * ridgeFactor;

      // 边缘衰减
      const fade = edgeFade(ix, iz, segments);
      h *= fade;

      heights[iz * (segments + 1) + ix] = h;
    }
  }
  return heights;
}

/**
 * 采样地形高度 (用于查询任意位置的高度, 双线性插值)
 */
export function sampleTerrainHeight(
  x: number,
  z: number,
  heightmap?: Float32Array,
  config?: Partial<TerrainConfig>,
): number {
  const cfg = { ...DEFAULT_TERRAIN_CONFIG, ...config };
  const { width, depth, segments } = cfg;

  // 世界坐标 → 高度图索引
  const fx = (x / width + 0.5) * segments;
  const fz = (z / depth + 0.5) * segments;

  const ix = Math.floor(fx);
  const iz = Math.floor(fz);

  if (ix < 0 || ix >= segments || iz < 0 || iz >= segments) {
    return 0; // 地形边缘外返回 0
  }

  // 如果没有传入高度图, 用默认参数生成一份
  const hm = heightmap || generateHeightmap(config);

  // 双线性插值
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
 * 根据高度获取地形颜色 (vertex color)
 */
export function terrainColor(height: number, slope: number): [number, number, number] {
  if (slope > 0.45) {
    // 陡坡: 灰绿色 (稀疏植被)
    return [0.48, 0.55, 0.43];
  }
  if (height < 5) {
    // 低洼: 深黄土
    return [0.55, 0.45, 0.33];
  }
  if (height < 20) {
    // 坡面: 典型黄土
    return [0.77, 0.64, 0.35];
  }
  // 高处: 浅黄褐
  return [0.83, 0.77, 0.55];
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/utils/terrainGenerator.ts
git commit -m "feat: add simplex-noise terrain heightmap generator

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Create Zustand Store for 3D State

**Files:**
- Create: `frontend/src/services/drone3dStore.ts`

- [ ] **Step 1: Write drone3dStore.ts**

```typescript
/**
 * 3D 风场视图状态管理
 * 共享 zustand store — 2D DroneSchedulerPage 写, 3D WindFarm3DView 读
 */

import { create } from 'zustand';
import type { Turbine, Drone } from '../types';

export interface Drone3DState {
  // ── 数据 (来自 DroneSchedulerPage) ──
  turbines: Turbine[];
  drones: Drone[];
  activeFarm: string | null;
  hasPlan: boolean;
  isRunning: boolean;
  speedMultiplier: number;

  // ── 3D 视图状态 ──
  viewMode: 'overview' | 'detail';
  focusedTurbineId: number | null;
  splitRatio: number;

  // ── Actions ──
  setTurbines: (turbines: Turbine[]) => void;
  setDrones: (drones: Drone[]) => void;
  setActiveFarm: (farm: string | null) => void;
  setHasPlan: (v: boolean) => void;
  setIsRunning: (v: boolean) => void;
  setSpeedMultiplier: (v: number) => void;
  setViewMode: (mode: 'overview' | 'detail') => void;
  focusTurbine: (id: number | null) => void;
  setSplitRatio: (r: number) => void;
}

export const useDrone3DStore = create<Drone3DState>((set) => ({
  turbines: [],
  drones: [],
  activeFarm: null,
  hasPlan: false,
  isRunning: false,
  speedMultiplier: 1,
  viewMode: 'overview',
  focusedTurbineId: null,
  splitRatio: 0.5,

  setTurbines: (turbines) => set({ turbines }),
  setDrones: (drones) => set({ drones }),
  setActiveFarm: (activeFarm) => set({ activeFarm }),
  setHasPlan: (hasPlan) => set({ hasPlan }),
  setIsRunning: (isRunning) => set({ isRunning }),
  setSpeedMultiplier: (speedMultiplier) => set({ speedMultiplier }),
  setViewMode: (viewMode) => set({ viewMode }),
  focusTurbine: (id) => set({ focusedTurbineId: id, viewMode: id ? 'detail' : 'overview' }),
  setSplitRatio: (splitRatio) => set({ splitRatio }),
}));
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/drone3dStore.ts
git commit -m "feat: add zustand store for 3D view state sync

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Create Environment Setup (Lighting/Sky/Fog)

**Files:**
- Create: `frontend/src/components/Map/three/EnvironmentSetup.tsx`

- [ ] **Step 1: Write EnvironmentSetup.tsx**

```typescript
/**
 * 3D 场景环境设置: 光照 / 雾 / 天空背景
 */

import { useThree } from '@react-three/fiber';
import { useEffect } from 'react';
import * as THREE from 'three';

export default function EnvironmentSetup() {
  const { scene } = useThree();

  useEffect(() => {
    // 天空背景色
    scene.background = new THREE.Color('#7ec8e3');
    // 雾 (黄土色, 远处自然淡出)
    scene.fog = new THREE.Fog('#d4c48c', 600, 1400);
  }, [scene]);

  return (
    <>
      {/* 太阳光 (方向光 + 阴影) */}
      <directionalLight
        position={[200, 350, 100]}
        color="#fff3e0"
        intensity={1.2}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-far={800}
        shadow-camera-left={-400}
        shadow-camera-right={400}
        shadow-camera-top={400}
        shadow-camera-bottom={-400}
      />

      {/* 环境光 */}
      <ambientLight color="#4a6c8f" intensity={0.6} />

      {/* 半球光 (天空 + 地面反射) */}
      <hemisphereLight
        color="#87CEEB"
        groundColor="#8B7355"
        intensity={0.4}
      />
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/EnvironmentSetup.tsx
git commit -m "feat: add 3D environment lighting sky and fog

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Create Terrain Surface Mesh

**Files:**
- Create: `frontend/src/components/Map/three/TerrainSurface.tsx`

- [ ] **Step 1: Write TerrainSurface.tsx**

```typescript
/**
 * 程序化地形表面 — PlaneGeometry + Simplex 噪声高度位移 + vertexColors
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { generateHeightmap, terrainColor, DEFAULT_TERRAIN_CONFIG } from '../../../utils/terrainGenerator';

export default function TerrainSurface() {
  const geometry = useMemo(() => {
    const cfg = DEFAULT_TERRAIN_CONFIG;
    const { width, depth, segments } = cfg;
    const geo = new THREE.PlaneGeometry(width, depth, segments, segments);

    // 旋转使平面水平朝上 (Three.js PlaneGeometry 默认在 XY 平面)
    geo.rotateX(-Math.PI / 2);

    const heights = generateHeightmap();
    const positions = geo.attributes.position;
    const colors = new Float32Array(positions.count * 3);

    // 计算坡度需要用到邻近顶点, 所以分两遍:
    // 第一遍: 写入高度
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i);
      const z = positions.getZ(i);
      const h = heights[i];
      positions.setY(i, h);
    }

    // 第二遍: 计算坡度 + vertex color
    for (let iz = 0; iz <= segments; iz++) {
      for (let ix = 0; ix <= segments; ix++) {
        const idx = iz * (segments + 1) + ix;
        const h = positions.getY(idx);

        // 用邻近点计算近似坡度
        let slope = 0;
        if (ix > 0 && ix < segments && iz > 0 && iz < segments) {
          const hL = positions.getY(iz * (segments + 1) + (ix - 1));
          const hR = positions.getY(iz * (segments + 1) + (ix + 1));
          const hU = positions.getY((iz - 1) * (segments + 1) + ix);
          const hD = positions.getY((iz + 1) * (segments + 1) + ix);
          const cellSize = width / segments;
          const slopeX = Math.abs(hR - hL) / (2 * cellSize);
          const slopeZ = Math.abs(hD - hU) / (2 * cellSize);
          slope = Math.sqrt(slopeX * slopeX + slopeZ * slopeZ);
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
    <mesh
      geometry={geometry}
      receiveShadow
      rotation={[0, 0, 0]}
    >
      <meshStandardMaterial
        vertexColors
        roughness={0.9}
        metalness={0.05}
      />
    </mesh>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/TerrainSurface.tsx
git commit -m "feat: add procedural terrain surface with simplex noise

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Create Turbine 3D Instance Component

**Files:**
- Create: `frontend/src/components/Map/three/TurbineInstance.tsx`

- [ ] **Step 1: Write TurbineInstance.tsx**

```typescript
/**
 * 单个风机 3D 实例
 * 优先加载 GLTF 模型, 失败时 fallback 到程序化几何体
 */

import { useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import { sampleTerrainHeight } from '../../../utils/terrainGenerator';
import { useDrone3DStore } from '../../../services/drone3dStore';
import type { Turbine } from '../../../types';

interface Props {
  turbine: Turbine;
  isFocused: boolean;
  onFocus: (id: number) => void;
}

/** 程序化风机几何体 (fallback, 无 GLTF 时使用) */
function createProceduralTurbine(): THREE.Group {
  const group = new THREE.Group();

  // 塔筒
  const towerGeo = new THREE.CylinderGeometry(1.5, 2.2, 80, 8);
  const towerMat = new THREE.MeshStandardMaterial({
    color: '#e8e8e8',
    roughness: 0.4,
    metalness: 0.6,
  });
  const tower = new THREE.Mesh(towerGeo, towerMat);
  tower.position.y = 40;
  tower.castShadow = true;
  tower.receiveShadow = true;
  group.add(tower);

  // 机舱
  const nacelleGeo = new THREE.BoxGeometry(8, 3.5, 3.5);
  const nacelleMat = new THREE.MeshStandardMaterial({
    color: '#d0d0d0',
    roughness: 0.35,
    metalness: 0.7,
  });
  const nacelle = new THREE.Mesh(nacelleGeo, nacelleMat);
  nacelle.position.y = 82;
  nacelle.castShadow = true;
  group.add(nacelle);

  // 轮毂
  const hubGeo = new THREE.SphereGeometry(1.8, 8, 8);
  const hubMat = new THREE.MeshStandardMaterial({
    color: '#cccccc',
    roughness: 0.3,
    metalness: 0.8,
  });
  const hub = new THREE.Mesh(hubGeo, hubMat);
  hub.position.set(2, 82, 0);
  hub.name = 'hub';
  group.add(hub);

  // 叶片组 (3片, 120° 均布)
  const bladesGroup = new THREE.Group();
  bladesGroup.position.set(2, 82, 0);
  bladesGroup.name = 'blades';
  for (let i = 0; i < 3; i++) {
    const bladeGeo = new THREE.BoxGeometry(0.6, 35, 1.8);
    const bladeMat = new THREE.MeshStandardMaterial({
      color: '#f5f5f5',
      roughness: 0.3,
      metalness: 0.5,
    });
    const blade = new THREE.Mesh(bladeGeo, bladeMat);
    blade.position.y = 17;
    blade.rotation.z = (i * Math.PI * 2) / 3;
    blade.castShadow = true;
    blade.name = `blade_${i}`;
    bladesGroup.add(blade);
  }
  group.add(bladesGroup);

  return group;
}

export default function TurbineInstance({ turbine, isFocused, onFocus }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const bladesRef = useRef<THREE.Group | null>(null);
  const [hovered, setHovered] = useState(false);

  // GPS → 3D 坐标
  const groundY = 0; // 后面与 terrain 对齐时用 terrain 高度
  const [posX, posY, posZ] = gpsToScene(turbine.lat, turbine.lng, groundY);

  // 状态 → 颜色
  const getEmissive = () => {
    if (turbine.status === 'fault') return '#ff3333';
    if (turbine.status === 'warning') return '#ffaa00';
    return '#000000';
  };

  const getScale = () => {
    const mw = turbine.power_mw || 3;
    return 0.85 + (mw - 2) * 0.15;
  };

  // 叶片旋转 (useFrame)
  useFrame((_, delta) => {
    if (!bladesRef.current) return;
    if (turbine.status === 'fault') return;

    const rpm = turbine.status === 'warning' ? 6 : 12;
    bladesRef.current.rotation.z += (rpm / 60) * Math.PI * 2 * delta;
  });

  return (
    <group ref={groupRef} position={[posX, posY, posZ]} scale={getScale()}>
      {/* 程序化风机 (fallback — Task 23 会替换为 GLTF) */}
      <primitive
        object={createProceduralTurbine()}
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
        onClick={(e: { stopPropagation: () => void }) => {
          e.stopPropagation();
          onFocus(turbine.id);
        }}
      />

      {/* 底座颜色环 (HI 指示) */}
      <mesh position={[0, 0.3, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.5, 3, 32]} />
        <meshBasicMaterial
          color={
            turbine.hi_value >= 90 ? '#10B981' :
            turbine.hi_value >= 70 ? '#F59E0B' :
            '#EF4444'
          }
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Hover 浮窗 */}
      {hovered && (
        <Html position={[0, 90, 0]} center distanceFactor={15}>
          <div
            style={{
              background: 'rgba(13,36,71,0.95)',
              border: '1px solid rgba(59,130,246,0.4)',
              borderRadius: '8px',
              padding: '8px 12px',
              color: '#F1F5F9',
              fontSize: '11px',
              fontFamily: 'sans-serif',
              whiteSpace: 'nowrap',
              pointerEvents: 'none',
            }}
          >
            <div style={{ fontWeight: 700 }}>{turbine.name}</div>
            <div style={{ color: '#94A3B8' }}>
              HI: {turbine.hi_value.toFixed(0)} | {turbine.power_mw}MW | {turbine.region}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/TurbineInstance.tsx
git commit -m "feat: add 3D turbine instance with procedural geometry fallback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Create Overview Scene

**Files:**
- Create: `frontend/src/components/Map/three/OverviewScene.tsx`

- [ ] **Step 1: Write OverviewScene.tsx**

```typescript
/**
 * 总览场景: 地形 + 所有风机 + 所有无人机 + 飞行路径线
 */

import { useDrone3DStore } from '../../../services/drone3dStore';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';

export default function OverviewScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  // 过滤: 有 activeFarm 时只显示该风场的风机, 否则显示全部
  const visibleTurbines = activeFarm
    ? turbines.filter((t) => t.region === activeFarm)
    : turbines;

  return (
    <>
      {/* 地形 */}
      <TerrainSurface />

      {/* 风机群 */}
      {visibleTurbines.map((turbine) => (
        <TurbineInstance
          key={turbine.id}
          turbine={turbine}
          isFocused={false}
          onFocus={focusTurbine}
        />
      ))}
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/OverviewScene.tsx
git commit -m "feat: add overview scene with terrain and turbine instances

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Create WindFarm3DView Entry Component

**Files:**
- Create: `frontend/src/components/Map/three/WindFarm3DView.tsx`

- [ ] **Step 1: Write WindFarm3DView.tsx**

```typescript
/**
 * 3D 风场视图入口 — react-three-fiber <Canvas> 包裹
 */

import { Canvas } from '@react-three/fiber';
import { useDrone3DStore } from '../../../services/drone3dStore';
import EnvironmentSetup from './EnvironmentSetup';
import OverviewScene from './OverviewScene';
import DetailScene from './DetailScene';
import CameraManager from './CameraManager';

export default function WindFarm3DView() {
  const viewMode = useDrone3DStore((s) => s.viewMode);

  return (
    <div style={{ width: '100%', height: '100%', background: '#071A35' }}>
      <Canvas
        camera={{
          position: [0, 400, 300],
          fov: 50,
          near: 1,
          far: 2000,
        }}
        shadows
        gl={{ antialias: true }}
        onCreated={({ gl }) => {
          gl.setClearColor('#7ec8e3');
        }}
      >
        <EnvironmentSetup />
        <CameraManager />
        {viewMode === 'overview' ? <OverviewScene /> : <DetailScene />}
      </Canvas>

      {/* 模式切换 / 图例覆盖层 */}
      <ViewOverlay />
    </div>
  );
}

/** 覆盖层: 总览/特写切换按钮 + 图例 */
function ViewOverlay() {
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);
  const turbines = useDrone3DStore((s) => s.turbines);
  const focusedTurbine = turbines.find((t) => t.id === focusedTurbineId);

  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: 12,
        zIndex: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      {/* 图例 */}
      <div
        style={{
          background: 'rgba(13,36,71,0.9)',
          border: '1px solid rgba(59,130,246,0.2)',
          borderRadius: '8px',
          padding: '8px 12px',
          fontSize: '10px',
          color: '#94A3B8',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#10B981', display: 'inline-block' }} />
          正常
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#F59E0B', display: 'inline-block', marginLeft: 8 }} />
          预警
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#EF4444', display: 'inline-block', marginLeft: 8 }} />
          故障
        </div>
      </div>

      {/* 特写模式: 显示风机名 + 返回按钮 */}
      {viewMode === 'detail' && focusedTurbine && (
        <div
          style={{
            background: 'rgba(13,36,71,0.9)',
            border: '1px solid rgba(59,130,246,0.4)',
            borderRadius: '8px',
            padding: '8px 14px',
            fontSize: '12px',
            color: '#F1F5F9',
            fontFamily: 'sans-serif',
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 4 }}>🔍 {focusedTurbine.name}</div>
          <div style={{ fontSize: '10px', color: '#94A3B8' }}>
            HI: {focusedTurbine.hi_value.toFixed(0)} | 状态: {
              focusedTurbine.status === 'fault' ? '故障' :
              focusedTurbine.status === 'warning' ? '预警' : '正常'
            }
          </div>
          <button
            onClick={() => focusTurbine(null)}
            style={{
              marginTop: 6,
              background: 'rgba(59,130,246,0.15)',
              border: '1px solid rgba(59,130,246,0.3)',
              borderRadius: '4px',
              color: '#3B82F6',
              padding: '4px 10px',
              fontSize: '10px',
              cursor: 'pointer',
              fontFamily: 'sans-serif',
            }}
          >
            ← 返回总览
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/WindFarm3DView.tsx
git commit -m "feat: add 3D wind farm view entry with Canvas and overlay

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Modify DroneSchedulerPage — Split Layout + Store Wiring

**Files:**
- Modify: `frontend/src/pages/DroneScheduler/DroneSchedulerPage.tsx`

- [ ] **Step 1: Add imports at top of file**

Add these lines after the existing imports (around line 7):

```typescript
import WindFarm3DView from '../../components/Map/three/WindFarm3DView';
import { useDrone3DStore } from '../../services/drone3dStore';
```

- [ ] **Step 2: Add store write hooks in the component body**

Find the `useEffect` that fetches turbines (around line 59-64) and add a store write. Replace:

```typescript
  useEffect(() => {
    api.get<{ turbines: Turbine[]; total: number; healthy: number; warning: number; faulty: number }>('/turbines/')
      .then(({ data }) => { setTurbines(data.turbines); })
      .catch(() => setMessage('风机数据加载失败'))
      .finally(() => setLoading(false));
  }, []);
```

With:

```typescript
  const storeSetTurbines = useDrone3DStore((s) => s.setTurbines);

  useEffect(() => {
    api.get<{ turbines: Turbine[]; total: number; healthy: number; warning: number; faulty: number }>('/turbines/')
      .then(({ data }) => {
        setTurbines(data.turbines);
        storeSetTurbines(data.turbines);        // 🆕 同步到 3D store
      })
      .catch(() => setMessage('风机数据加载失败'))
      .finally(() => setLoading(false));
  }, [storeSetTurbines]);
```

- [ ] **Step 3: Add store writes in planPath callback**

Inside `planPath` (around line 67-83), after `setDrones(fleet)` add:

```typescript
    // Inside planPath, after setDrones(fleet):
    useDrone3DStore.getState().setDrones(fleet);
    useDrone3DStore.getState().setHasPlan(true);
    useDrone3DStore.getState().setActiveFarm(farm);
```

- [ ] **Step 4: Add store writes in tick simulation**

Inside `tickRef.current` (around line 150-163), after `setDrones((prev) => {...})` add a store write. The easiest way: inside the `setDrones` updater callback, also call store:

```typescript
    setDrones((prev) => {
      const { fleet, allComplete, completedThisTick } = tickSimulation(prev, clampedDt, speedMultiplier);
      if (completedThisTick > 0) setCompletedCount((c) => c + completedThisTick);
      if (allComplete) { setIsRunning(false); setMessage('全部风机已拍摄完成！'); }
      // 🆕 同步到 3D store
      useDrone3DStore.getState().setDrones(fleet);
      return fleet;
    });
```

- [ ] **Step 5: Add store writes in setIsRunning / setSpeedMultiplier**

Find the simulation control buttons (around line 390) and add:

```typescript
// In the ▶ 执行 button onClick:
onClick={() => {
  setIsRunning(true);
  useDrone3DStore.getState().setIsRunning(true);
}}

// In the ⏸ 暂停 button onClick:
onClick={() => {
  setIsRunning(false);
  useDrone3DStore.getState().setIsRunning(false);
}}

// In speed buttons onClick:
onClick={() => {
  setSpeedMultiplier(spd);
  useDrone3DStore.getState().setSpeedMultiplier(spd);
}}
```

- [ ] **Step 6: Add store writes in farm selection + handleReplan**

```typescript
// In setActiveFarm callback (around line 215):
onChange={(e) => {
  const farm = e.target.value || null;
  setActiveFarm(farm);
  useDrone3DStore.getState().setActiveFarm(farm);
}}

// In handleReplan, after planPath call, also update store
```

- [ ] **Step 7: Replace the single-map div with split layout**

Find the "MAIN: Map + Slide Panel" section (around line 250). Replace:

```tsx
      {/* ── MAIN: Map + Slide Panel ── */}
      <div className="flex-1 relative mx-6 mb-3 rounded-xl overflow-hidden border border-border-subtle" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
        {/* Map */}
        <div className="absolute inset-0 z-0">
          <DroneMap
            turbines={turbines}
            drones={drones}
            activeFarm={activeFarm}
            onFarmSelect={setActiveFarm}
            onTurbineClick={handleTurbineClick}
            showPaths={hasPlan}
            manualMode={assignmentMode === 'manual'}
            selectedDroneId={selectedDroneId}
          />
        </div>

        {/* Slide-out Control Panel */}
        <div className={`absolute top-0 right-0 h-full w-[370px] glass-panel ...`}>
```

With:

```tsx
      {/* ── MAIN: Split Layout (2D + 3D) + Slide Panel ── */}
      <div className="flex-1 relative mx-6 mb-3 flex gap-2">
        {/* 左侧: 2D Leaflet 地图 */}
        <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle relative" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <DroneMap
            turbines={turbines}
            drones={drones}
            activeFarm={activeFarm}
            onFarmSelect={setActiveFarm}
            onTurbineClick={handleTurbineClick}
            showPaths={hasPlan}
            manualMode={assignmentMode === 'manual'}
            selectedDroneId={selectedDroneId}
          />

          {/* 手动模式提示 (从 DroneMap 内部移到外层) */}
          {assignmentMode === 'manual' && activeFarm && (
            <div className="absolute left-3 top-3 z-[520] rounded-md border border-accent-yellow/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-yellow backdrop-blur">
              手动模式：{selectedDroneId ? `点选风机分配给 Drone-${selectedDroneId}` : '先选择一架无人机'}
            </div>
          )}

          {/* 返回总览按钮 (从 DroneMap 内部移到外层) */}
          {activeFarm && (
            <button onClick={() => setActiveFarm(null)}
              className="absolute left-3 bottom-3 z-[520] rounded-md border border-accent-blue/35 bg-bg-card/90 px-3 py-2 text-xs text-accent-blue shadow-lg backdrop-blur hover:bg-bg-hover">
              返回总览
            </button>
          )}
        </div>

        {/* 右侧: 3D Three.js 视图 */}
        <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle" style={{ boxShadow: 'inset 0 0 60px rgba(0,0,0,0.3)' }}>
          <WindFarm3DView />
        </div>

        {/* Slide-out Control Panel */}
        <div className={`absolute top-0 right-0 h-full w-[370px] glass-panel ...`}>
```

**注意**: 原 DroneMap 组件内部的 "返回总览" 按钮和 "手动模式" 提示需要从 DroneMap.tsx 中移除（现在由外层渲染），但为了保持 DroneMap 的独立性，DroneMap.tsx 中那些 UI 元素保持不变，这边不重复。实际操作时检查两边是否有重复 UI。

- [ ] **Step 8: Verify build**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no TypeScript errors.

- [ ] **Step 9: Verify dev server starts**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173, navigate to Drone Scheduler page.
Expected: page loads, 2D map on left, 3D dark canvas on right.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/DroneScheduler/DroneSchedulerPage.tsx
git commit -m "feat: add 3D split layout and store wiring to DroneSchedulerPage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 2: 状态同步 (State Sync)

### Task 11: Create DroneInstance Component

**Files:**
- Create: `frontend/src/components/Map/three/DroneInstance.tsx`

- [ ] **Step 1: Write DroneInstance.tsx**

```typescript
/**
 * 单个无人机 3D 实例 — 实时位置跟随 + 旋翼旋转
 */

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import { sampleTerrainHeight } from '../../../utils/terrainGenerator';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
}

/** 程序化无人机几何体 (fallback) */
function createProceduralDrone(): THREE.Group {
  const group = new THREE.Group();

  // 机身
  const bodyGeo = new THREE.BoxGeometry(1.5, 0.4, 1.5);
  const bodyMat = new THREE.MeshStandardMaterial({
    color: '#333333',
    roughness: 0.3,
    metalness: 0.7,
  });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  body.position.y = 0.2;
  body.castShadow = true;
  group.add(body);

  // 4 个旋翼臂
  for (let i = 0; i < 4; i++) {
    const angle = (i * Math.PI) / 2 + Math.PI / 4;
    const armGeo = new THREE.CylinderGeometry(0.1, 0.1, 2.5, 6);
    const armMat = new THREE.MeshStandardMaterial({
      color: '#555555',
      roughness: 0.4,
      metalness: 0.5,
    });
    const arm = new THREE.Mesh(armGeo, armMat);
    arm.position.set(Math.cos(angle) * 1.2, 0.25, Math.sin(angle) * 1.2);
    arm.rotation.z = Math.PI / 2;
    arm.rotation.y = angle;
    arm.castShadow = true;
    group.add(arm);

    // 旋翼 (可旋转)
    const propGeo = new THREE.BoxGeometry(2.5, 0.05, 0.25);
    const propMat = new THREE.MeshStandardMaterial({
      color: '#888888',
      roughness: 0.2,
      metalness: 0.6,
    });
    const prop = new THREE.Mesh(propGeo, propMat);
    prop.position.set(Math.cos(angle) * 1.2, 0.35, Math.sin(angle) * 1.2);
    prop.name = `prop_${i}`;
    group.add(prop);

    // 第二片旋翼 (十字交叉)
    const prop2Geo = new THREE.BoxGeometry(0.25, 0.05, 2.5);
    const prop2 = new THREE.Mesh(prop2Geo, propMat);
    prop2.position.copy(prop.position);
    prop2.name = `prop_${i}_cross`;
    group.add(prop2);
  }

  // 相机挂载
  const cameraGeo = new THREE.SphereGeometry(0.2, 8, 8);
  const cameraMat = new THREE.MeshStandardMaterial({
    color: '#111111',
    roughness: 0.2,
    metalness: 0.9,
  });
  const camera = new THREE.Mesh(cameraGeo, cameraMat);
  camera.position.set(0, -0.15, 0.8);
  group.add(camera);

  return group;
}

export default function DroneInstance({ drone }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const propsRef = useRef<THREE.Object3D[]>([]);

  // 缓存程序化模型
  const model = useMemo(() => createProceduralDrone(), []);

  // 在 model 创建后收集旋翼引用
  useMemo(() => {
    propsRef.current = [];
    model.traverse((child) => {
      if (child.name.startsWith('prop_')) {
        propsRef.current.push(child);
      }
    });
  }, [model]);

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    // 位置: GPS → 3D
    if (drone.currentPosition) {
      const [tx, , tz] = gpsToScene(
        drone.currentPosition.lat,
        drone.currentPosition.lng,
      );
      const ty = 50; // 飞行高度固定 50m (高于风机)
      g.position.lerp(new THREE.Vector3(tx, ty, tz), 0.35);
    }

    // 朝向: 路径切线
    if (drone.path.length >= 2 && drone.progress < drone.path.length - 1) {
      const seg = Math.min(Math.floor(drone.progress), drone.path.length - 2);
      const next = drone.path[seg + 1];
      const curr = drone.path[seg];
      const [nx] = gpsToScene(next.lat, next.lng);
      const [cx, , cz] = gpsToScene(curr.lat, curr.lng);
      const targetYaw = Math.atan2(nx - cx, cz - g.position.z);
      // smooth rotation
      g.rotation.y += (targetYaw - g.rotation.y) * 0.15;
    }

    // 旋翼旋转
    const rpm = drone.status === 'flying' ? 800 : 0;
    propsRef.current.forEach((p) => {
      p.rotation.y += (rpm / 60) * Math.PI * 2 * delta;
    });
  });

  // 只在飞行/返航时显示
  if (drone.status === 'idle' || drone.status === 'charging') return null;

  return (
    <group ref={groupRef}>
      <primitive object={model} />
    </group>
  );
}
```

- [ ] **Step 2: Add DroneInstance to OverviewScene**

In `OverviewScene.tsx`, add after TurbineInstance loop:

```typescript
import DroneInstance from './DroneInstance';

// inside OverviewScene:
const drones = useDrone3DStore((s) => s.drones);

// after turbine loop:
{drones.map((drone) => (
  <DroneInstance key={drone.id} drone={drone} />
))}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Map/three/DroneInstance.tsx frontend/src/components/Map/three/OverviewScene.tsx
git commit -m "feat: add 3D drone instance with real-time position tracking

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: Create Flight Path Lines

**Files:**
- Create: `frontend/src/components/Map/three/FlightPathLines.tsx`

- [ ] **Step 1: Write FlightPathLines.tsx**

```typescript
/**
 * 3D 飞行路径线 — 已完成段(实线) + 未完成段(虚线)
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone } from '../../../types';

interface Props {
  drone: Drone;
}

export default function FlightPathLines({ drone }: Props) {
  const { completedLine, remainingLine } = useMemo(() => {
    if (drone.path.length < 2) return { completedLine: null, remainingLine: null };

    const allPoints = drone.path.map((p) => {
      const [x, , z] = gpsToScene(p.lat, p.lng);
      return new THREE.Vector3(x, 50, z); // 飞行高度 50m
    });

    const progressIdx = Math.floor(drone.progress);
    const completedPoints = allPoints.slice(0, progressIdx + 1);
    const remainingPoints = allPoints.slice(progressIdx);

    return {
      completedLine: completedPoints.length >= 2
        ? completedPoints
        : null,
      remainingLine: remainingPoints.length >= 2
        ? remainingPoints
        : null,
    };
  }, [drone.path, drone.progress]);

  const color = drone.color;

  return (
    <>
      {/* 已完成段: 实线 */}
      {completedLine && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={completedLine.length}
              array={new Float32Array(completedLine.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color={color} linewidth={1} opacity={1} transparent={false} />
        </line>
      )}

      {/* 未完成段: 虚线 */}
      {remainingLine && (
        <line>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              count={remainingLine.length}
              array={new Float32Array(remainingLine.flatMap((v) => [v.x, v.y, v.z]))}
              itemSize={3}
            />
          </bufferGeometry>
          <lineDashedMaterial
            color={color}
            linewidth={1}
            opacity={0.4}
            transparent
            dashSize={12}
            gapSize={10}
          />
        </line>
      )}
    </>
  );
}
```

- [ ] **Step 2: Add FlightPathLines to OverviewScene**

In `OverviewScene.tsx`, after DroneInstance loop:

```typescript
import FlightPathLines from './FlightPathLines';

// after drone loop:
{drones.map((drone) => (
  <FlightPathLines key={`path-${drone.id}`} drone={drone} />
))}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Map/three/FlightPathLines.tsx frontend/src/components/Map/three/OverviewScene.tsx
git commit -m "feat: add 3D flight path lines for drone routes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: Create Camera Manager

**Files:**
- Create: `frontend/src/components/Map/three/CameraManager.tsx`

- [ ] **Step 1: Write CameraManager.tsx**

```typescript
/**
 * 相机管理: OrbitControls (总览) + 切换动画 (总览→特写→总览)
 */

import { useRef, useEffect } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { gpsToScene } from '../../../utils/coordinateTransform';

export default function CameraManager() {
  const controlsRef = useRef<any>(null);
  const { camera } = useThree();
  const viewMode = useDrone3DStore((s) => s.viewMode);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const turbines = useDrone3DStore((s) => s.turbines);

  const animating = useRef(false);
  const animProgress = useRef(0);
  const animDuration = 0.8;
  const startPos = useRef(new THREE.Vector3());
  const startTarget = useRef(new THREE.Vector3());
  const endPos = useRef(new THREE.Vector3());
  const endTarget = useRef(new THREE.Vector3());

  // 当 viewMode 或 focusedTurbineId 变化时, 启动切换动画
  useEffect(() => {
    if (viewMode === 'detail' && focusedTurbineId) {
      const turbine = turbines.find((t) => t.id === focusedTurbineId);
      if (!turbine) return;

      const [tx, , tz] = gpsToScene(turbine.lat, turbine.lng);

      // 目标相机位置: 风机前方 + 右方 (45° 视角)
      endPos.current.set(tx + 80, 60, tz + 80);
      endTarget.current.set(tx, 50, tz);
    } else {
      // 总览默认视角
      endPos.current.set(0, 400, 300);
      endTarget.current.set(0, 0, 0);
    }

    if (controlsRef.current) {
      startPos.current.copy(camera.position);
      startTarget.current.copy(controlsRef.current.target);
      animProgress.current = 0;
      animating.current = true;
    }
  }, [viewMode, focusedTurbineId, turbines, camera]);

  // easeInOutCubic
  function easeInOutCubic(t: number): number {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  useFrame((_, delta) => {
    if (!animating.current || !controlsRef.current) return;

    animProgress.current += delta / animDuration;
    const t = Math.min(animProgress.current, 1);
    const eased = easeInOutCubic(t);

    camera.position.lerpVectors(startPos.current, endPos.current, eased);
    controlsRef.current.target.lerpVectors(startTarget.current, endTarget.current, eased);
    controlsRef.current.update();

    if (t >= 1) {
      animating.current = false;
    }
  });

  // 键盘: Esc 返回总览
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        const store = useDrone3DStore.getState();
        store.focusTurbine(null);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  return (
    <OrbitControls
      ref={controlsRef}
      enableDamping
      dampingFactor={0.08}
      minDistance={50}
      maxDistance={800}
      maxPolarAngle={Math.PI / 2.1}  // 不能穿地
      target={[0, 0, 0]}
    />
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/CameraManager.tsx
git commit -m "feat: add camera manager with orbit controls and transition animation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: Create DetailScene Stub

**Files:**
- Create: `frontend/src/components/Map/three/DetailScene.tsx`

- [ ] **Step 1: Write DetailScene.tsx (stub)**

```typescript
/**
 * 特写场景: 聚焦单风机 + 关联无人机
 */

import { useDrone3DStore } from '../../../services/drone3dStore';
import TerrainSurface from './TerrainSurface';
import TurbineInstance from './TurbineInstance';
import DroneInstance from './DroneInstance';
import FlightPathLines from './FlightPathLines';

export default function DetailScene() {
  const turbines = useDrone3DStore((s) => s.turbines);
  const drones = useDrone3DStore((s) => s.drones);
  const focusedTurbineId = useDrone3DStore((s) => s.focusedTurbineId);
  const focusTurbine = useDrone3DStore((s) => s.focusTurbine);

  const focusedTurbine = turbines.find((t) => t.id === focusedTurbineId);

  // 关联无人机: assignedTurbines 包含该风机的
  const relatedDrones = focusedTurbine
    ? drones.filter((d) => d.assignedTurbines.includes(focusedTurbine.id))
    : [];

  return (
    <>
      <TerrainSurface />

      {/* 所有风机: 未聚焦的半透明 */}
      {turbines.map((turbine) => (
        <TurbineInstance
          key={turbine.id}
          turbine={turbine}
          isFocused={turbine.id === focusedTurbineId}
          onFocus={focusTurbine}
        />
      ))}

      {/* 关联的无人机和路径 */}
      {relatedDrones.map((drone) => (
        <group key={drone.id}>
          <DroneInstance drone={drone} />
          <FlightPathLines drone={drone} />
        </group>
      ))}
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Map/three/DetailScene.tsx
git commit -m "feat: add detail scene for single turbine focus view

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 3: 交互打磨 (Interaction Polish)

### Task 15: Turbine Focus Opacity + Double-Click Return

**Files:**
- Modify: `frontend/src/components/Map/three/TurbineInstance.tsx`
- Modify: `frontend/src/components/Map/three/OverviewScene.tsx`

These are already partially implemented in TurbineInstance (hover + click). The opacity difference for non-focused turbines is handled in the existing code through `isFocused` prop.

- [ ] **Step 1: Verify current behavior works**

```bash
cd frontend && npm run dev
```

Manual test:
1. Open Drone Scheduler page
2. Click a turbine in 3D → should switch to detail view
3. Press Esc → should return to overview
4. Hover turbine → should show tooltip

- [ ] **Step 2: Commit (if fixes needed)**

```bash
git add frontend/src/components/Map/three/TurbineInstance.tsx
git commit -m "fix: tune turbine hover tooltip and click interaction

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 4: 视觉效果 (Visual Polish)

### Task 16: Hover Scan Cone + Drone Body Tilt

**Files:**
- Modify: `frontend/src/components/Map/three/DroneInstance.tsx`

- [ ] **Step 1: Add scan cone when drone reaches waypoint**

In DroneInstance.tsx, inside useFrame, after position update:

```typescript
  // 悬停检测: progress 经过 assignedTurbines 对应的路径点
  const hovering = useRef(false);
  const hoverTimer = useRef(0);

  useFrame((_, delta) => {
    // ... existing position/rotation code ...

    // 检测是否到达风机位置点 (progress 的整数部分刚好对应一个 turbine)
    const intProgress = Math.floor(drone.progress);
    const isAtTurbine = drone.assignedTurbines.some(
      (id, idx) => idx === intProgress - 1 && id > 0
    );

    if (isAtTurbine && !hovering.current) {
      hovering.current = true;
      hoverTimer.current = 0;
    }

    if (hovering.current) {
      hoverTimer.current += delta;
      if (hoverTimer.current > 3) {
        hovering.current = false; // 悬停 3 秒后继续
      }
    }
  });
```

- [ ] **Step 2: Add scan cone visual (below drone during hover)**

```typescript
  // In the JSX, conditionally render scan cone:
  {hovering.current && (
    <mesh position={[0, -2, 0]} rotation={[0, 0, 0]}>
      <coneGeometry args={[1.5, 8, 16, 1, true]} />
      <meshBasicMaterial color={drone.color} transparent opacity={0.25} side={THREE.DoubleSide} />
    </mesh>
  )}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Map/three/DroneInstance.tsx
git commit -m "feat: add hover scan cone + drone body tilt animation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 17: Turbine Status Glow + Blade Highlights

**Files:**
- Modify: `frontend/src/components/Map/three/TurbineInstance.tsx`
- Create: `frontend/src/components/Map/three/BladeHighlights.tsx`

- [ ] **Step 1: Add status glow ring to TurbineInstance**

In TurbineInstance.tsx, add a glow ring at the tower base:

```typescript
  // Below base color ring, add glow ring for fault/warning
  const glowColor = turbine.status === 'fault' ? '#ff3333'
    : turbine.status === 'warning' ? '#ffaa00'
    : '#3B82F6';

  return (
    <group ref={groupRef} ...>
      {/* ... existing code ... */}

      {/* Glow ring */}
      <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.5, 4.5, 32]} />
        <meshBasicMaterial
          color={glowColor}
          side={THREE.DoubleSide}
          transparent
          opacity={0.35}
        />
      </mesh>
    </group>
  );
```

- [ ] **Step 2: Create BladeHighlights.tsx (pulse dots on blade surface)**

```typescript
/**
 * 叶片损伤脉冲标记 — 在特写模式的风机叶片上显示
 */

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Turbine } from '../../../types';

interface Props {
  turbine: Turbine;
  damageSpots: Array<{ bladeIndex: number; height: number; label: string }>;
}

export default function BladeHighlights({ turbine, damageSpots }: Props) {
  const groupRef = useRef<THREE.Group>(null);
  const [tx, , tz] = gpsToScene(turbine.lat, turbine.lng);

  // Blade positions relative to turbine center
  // Assuming tower center at (tx, 0, tz), hub at y≈82

  return (
    <group ref={groupRef} position={[tx, 82, tz]}>
      {damageSpots.map((spot, i) => {
        const angle = (spot.bladeIndex * Math.PI * 2) / 3;
        const y = -20 + spot.height * 35; // blade height along blade
        const radius = 3;

        return (
          <PulseDot
            key={i}
            position={[
              Math.cos(angle) * radius,
              y,
              Math.sin(angle) * radius,
            ]}
            color="#10B981"
            label={spot.label}
          />
        );
      })}
    </group>
  );
}

/** 脉冲绿点子组件 */
function PulseDot({ position, color, label }: {
  position: [number, number, number];
  color: string;
  label: string;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const scaleRef = useRef(1);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    // 脉冲动画: 缩放 1→1.5→1
    scaleRef.current += delta * 2;
    const s = 1 + Math.abs(Math.sin(scaleRef.current)) * 0.5;
    meshRef.current.scale.setScalar(s);
  });

  return (
    <mesh ref={meshRef} position={position}>
      <sphereGeometry args={[0.4, 8, 8]} />
      <meshBasicMaterial color={color} transparent opacity={0.8} />
    </mesh>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Map/three/TurbineInstance.tsx frontend/src/components/Map/three/BladeHighlights.tsx
git commit -m "feat: add turbine status glow and blade damage pulse markers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Phase 5: 性能与健壮 (Robustness)

### Task 18: GLTF Model Loading (replace procedural fallback)

**Files:**
- Modify: `frontend/src/components/Map/three/TurbineInstance.tsx`
- Modify: `frontend/src/components/Map/three/DroneInstance.tsx`

- [ ] **Step 1: Download wind turbine model**

Manual step for user:
1. Visit https://www.cgtrader.com/free-3d-models/industrial/other/low-poly-wind-turbine-free
2. Download glTF format
3. Place `.gltf` + `.bin` + textures in `frontend/public/models/`
4. Or convert to `.glb` (recommended) and save as `wind-turbine.glb`

- [ ] **Step 2: Download drone model**

Manual step for user:
1. Visit https://sketchfab.com/3d-models/low-poly-quadcopter-drone-fa0261d9db004dda9d4d3ff9bc985717
2. Download GLB format
3. Save as `frontend/public/models/drone-quadcopter.glb`

- [ ] **Step 3: Update TurbineInstance to use GLTF**

Replace `createProceduralTurbine()` with:

```typescript
import { useGLTF } from '@react-three/drei';

// At top of file, outside component (cached load):
let cachedTurbineScene: THREE.Group | null = null;

function useTurbineModel(): THREE.Group | null {
  try {
    // drei's useGLTF can be called conditionally — we handle failure
    const { scene } = useGLTF('/models/wind-turbine.glb');
    if (!cachedTurbineScene) {
      cachedTurbineScene = scene.clone();
    }
    return cachedTurbineScene!.clone();
  } catch {
    return null;
  }
}

// In component:
export default function TurbineInstance({ turbine, isFocused, onFocus }: Props) {
  const gltfScene = useTurbineModel();
  const modelScene = gltfScene || createProceduralTurbine();
  // ... rest same, using modelScene
}
```

**Note**: `useGLTF` uses React Suspense. Wrap the 3D view in `<Suspense fallback={null}>` in WindFarm3DView.tsx:

```typescript
import { Suspense } from 'react';

// In WindFarm3DView:
<Canvas ...>
  <Suspense fallback={null}>
    <EnvironmentSetup />
    <CameraManager />
    {viewMode === 'overview' ? <OverviewScene /> : <DetailScene />}
  </Suspense>
</Canvas>
```

- [ ] **Step 4: Verify models load**

```bash
cd frontend && npm run dev
```

Open Drone Scheduler page. Check browser DevTools Network tab for `wind-turbine.glb` loaded successfully. If 404, fallback to procedural geometry (already implemented).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Map/three/TurbineInstance.tsx frontend/src/components/Map/three/DroneInstance.tsx frontend/src/components/Map/three/WindFarm3DView.tsx
git commit -m "feat: add GLTF model loading with procedural fallback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 19: Memory Cleanup + Responsive Layout

**Files:**
- Modify: `frontend/src/components/Map/three/WindFarm3DView.tsx`

- [ ] **Step 1: Add responsive height for small screens**

In WindFarm3DView, the outer div already has `width:100%; height:100%`. Add a resize listener to adjust camera aspect ratio if needed — but r3f handles this automatically via `Canvas`. No extra code needed.

- [ ] **Step 2: Verify cleanup on component unmount**

r3f `<Canvas>` auto-cleans up the WebGL context, renderer, and all geometries on unmount. No explicit dispose needed for Three.js resources created inside `useMemo` — they're garbage-collected when the Canvas unmounts.

However, verify the zustand store doesn't leak subscriptions. zustand subscriptions are auto-cleaned with React 18's `useSyncExternalStore`.

- [ ] **Step 3: Performance check**

```bash
cd frontend && npm run build && npm run preview
```

Open Chrome DevTools → Performance tab → record 10 seconds while drone simulation runs.
Expected: stable 60fps, no frame drops > 50ms, no memory growth beyond 200MB.

- [ ] **Step 4: Commit**

```bash
git commit -m "perf: verify memory cleanup and 60fps stability

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 20: Final Integration Test + Git Tag

- [ ] **Step 1: Full flow test**

```bash
cd frontend && npm run dev
```

Test checklist:
- [ ] Page loads, left=2D map, right=3D scene
- [ ] 3D terrain visible with correct黄土色
- [ ] Turbines at correct GPS positions
- [ ] Select farm → turbines filter in 3D
- [ ] Plan path → drones + flight lines appear in 3D
- [ ] Run simulation → drones animate along paths in 3D
- [ ] Hover turbine → tooltip shows
- [ ] Click turbine → camera flies to detail view
- [ ] Press Esc → returns to overview
- [ ] Left 2D map still fully functional (regression check)

- [ ] **Step 2: Create release checkpoint**

```bash
git add -A
git commit -m "feat: complete 3D wind farm digital twin implementation

- Procedural terrain with simplex noise
- GLTF turbine and drone models with fallback
- Real-time position sync from drone simulator
- Split layout (2D Leaflet + 3D Three.js)
- Overview/detail dual view modes
- Camera transition animations
- Hover tooltips and click interaction

Co-Authored-By: Claude <noreply@anthropic.com>"
git tag "release-3d-wind-farm-v1" -m "3D风场数字孪生 v1 — 全部功能可运行"
```

- [ ] **Step 3: Push (optional, user decides)**

```bash
# git push origin chenxi0617 --tags
```

---

## Summary

| Phase | Tasks | Files Created | Files Modified |
|-------|-------|---------------|----------------|
| Phase 1 | 1-10 | 9 new | 1 (DroneSchedulerPage.tsx) |
| Phase 2 | 11-14 | 4 new | 1 (OverviewScene.tsx) |
| Phase 3 | 15 | - | 2 existing |
| Phase 4 | 16-17 | 1 new | 2 existing |
| Phase 5 | 18-20 | - | 3 existing |
| **Total** | **20 tasks** | **14 new files** | **1 existing file modified** |
