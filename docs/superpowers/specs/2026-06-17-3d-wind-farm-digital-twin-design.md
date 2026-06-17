# 3D 风场数字孪生 — 无人机巡检可视化增强

> 日期: 2026-06-17 | 版本: v1.0 | 状态: 设计阶段

---

## 1. 背景与目标

### 1.1 现状

风调预顺 PHM 系统已有完整的无人机调度模块（`DroneSchedulerPage`），基于 2D Leaflet 地图展示：

- 30 台风机的地理位置（陕北风场 A/B/C）
- 无人机 TSP/VRP 路径规划与动画仿真
- 叶片巡检图像的 YOLO 损伤检测

**2D 地图的局限**：
- 无法展示高度信息（无人机飞行高度、风机塔筒高度、地形起伏）
- 无人机用 22×22px 图标表示，缺乏视觉冲击力
- 叶片损伤位置只能在 2D 照片上标注，无法关联到风机的 3D 空间位置

### 1.2 目标

在 `DroneSchedulerPage` 中新增 **3D Three.js 辅助视图**，与现有 2D Leaflet 地图左右分屏，提供：

1. **3D 风场总览**：程序化地形 + 真实风机位置 + 无人机实时飞行动画
2. **单风机特写**：点击风机后相机飞近，展示叶片旋转 + 无人机绕飞路径
3. **数据完全同步**：3D 视图与 2D 地图共享同一份 zustand store，零硬编码

### 1.3 非目标

- 不替代现有 2D 地图（互补关系）
- 不在 3D 中做路径规划编辑（保持 2D 面板操作）
- 不引入外部地图瓦片服务依赖（地形程序化生成）

---

## 2. 技术方案

### 2.1 核心依赖

| 包 | 版本 | 用途 |
|---|------|------|
| `@react-three/fiber` | ^8.x | React 声明式 Three.js 封装 |
| `@react-three/drei` | ^9.x | 开箱即用工具（OrbitControls / useGLTF / Html / Sky） |
| `three` | ^0.170+ | WebGL 渲染引擎 |
| `simplex-noise` | ^4.x | 程序化地形高度图生成（3KB，零依赖） |

**不引入**：Mapbox GL、Cesium、Babylon.js、额外的 GIS 库。

### 2.2 3D 模型资源

#### 风机模型

| 属性 | 值 |
|------|-----|
| 来源 | [CGTrader — Low-Poly Wind Turbine (free)](https://www.cgtrader.com/free-3d-models/industrial/other/low-poly-wind-turbine-free) |
| 格式 | glTF (.gltf)，含纹理 |
| 面数 | ~941 faces / ~1,032 verts |
| 授权 | Royalty Free（可自由使用，含课程展示） |
| 结构 | 预期包含 Tower / Nacelle / Blades 三个独立节点 |
| 存放路径 | `frontend/public/models/wind-turbine.glb` |

#### 无人机模型

| 属性 | 值 |
|------|-----|
| 来源(首选) | [Sketchfab — Low Poly QuadCopter Drone (GTKima)](https://sketchfab.com/3d-models/low-poly-quadcopter-drone-fa0261d9db004dda9d4d3ff9bc985717) |
| 来源(备选) | [Sketchfab — Minimalist Drone Model (AlexseyZaporozhets)](https://sketchfab.com/3d-models/minimalist-drone-model-91b61a1bf68848f9aa0bee1ede4c79ec) |
| 格式 | GLB (.glb) |
| 面数 | 低面（游戏级） |
| 授权 | Sketchfab Free / CC-BY |
| 结构 | 预期包含机身 + 4 旋翼独立节点 |
| 存放路径 | `frontend/public/models/drone-quadcopter.glb` |

#### 模型加载说明

使用 drei 的 `useGLTF()` hook，一行加载：

```typescript
const { scene } = useGLTF('/models/wind-turbine.glb')
```

模型文件在 `public/` 目录下，Vite 开发服务器直接静态服务，生产构建时自动复制到 `dist/`。

模型下载后需要验证节点结构，如节点命名与预期不符，通过 `scene.getObjectByName()` + fallback 遍历适配。不假定节点名称，写健壮的查找逻辑。

---

## 3. 架构设计

### 3.1 文件结构

```
frontend/src/
├── components/Map/
│   ├── DroneMap.tsx                    # [不动] 现有 2D Leaflet 地图
│   ├── TurbineMap.tsx                  # [不动] 现有风机地图(仪表盘用)
│   └── three/                          # 🆕 Three.js 3D 子目录
│       ├── WindFarm3DView.tsx          #   3D 视图主入口 (<Canvas> 包裹)
│       ├── OverviewScene.tsx           #   总览场景 (地形+风机群+无人机群)
│       ├── DetailScene.tsx             #   特写场景 (单风机+绕飞无人机)
│       ├── TerrainSurface.tsx          #   程序化地形 mesh
│       ├── TurbineInstance.tsx         #   单个风机 3D 实例 (加载 GLTF + 状态映射)
│       ├── DroneInstance.tsx           #   单个无人机 3D 实例 (加载 GLB + 飞行动画)
│       ├── FlightPathLines.tsx         #   3D 飞行路径线 (已完成段+未完成段)
│       ├── BladeHighlights.tsx         #   叶片损伤标记 (脉冲绿点)
│       ├── EnvironmentSetup.tsx        #   光照/雾/天空背景
│       ├── CameraManager.tsx           #   相机控制 + 模式切换动画
│       ├── TurbineTooltip.tsx          #   3D 空间内风机信息浮窗 (drei Html)
│       └── ViewToggle.tsx             #   总览/特写切换 + 2D/3D 视图比例按钮
├── services/
│   └── drone3dStore.ts                # 🆕 zustand store (共享状态)
├── utils/
│   ├── coordinateTransform.ts         # 🆕 GPS → 3D 米制坐标转换
│   └── terrainGenerator.ts            # 🆕 Simplex 噪声地形高度图生成
├── types/
│   └── index.ts                        # [不动] 现有类型定义
└── pages/DroneScheduler/
    └── DroneSchedulerPage.tsx          # [修改] 引入 WindFarm3DView + 分屏布局
```

### 3.2 组件树

```
<DroneSchedulerPage>                       # 页面 (修改: 分屏布局)
  ├── <TopBar />                           # [不动]
  ├── <KPIStrip />                         # [不动]
  ├── <div className="split-view">         # 🆕 分屏容器
  │   ├── <DroneMap />                     # 左: 2D 地图 (不动)
  │   └── <WindFarm3DView>                 # 右: 3D 视图 (🆕)
  │       └── <Canvas>                     #   r3f Canvas
  │           ├── <EnvironmentSetup />     #   光照/雾/天空
  │           ├── <OverviewScene>          #   总览 (viewMode === 'overview')
  │           │   ├── <TerrainSurface />
  │           │   ├── <TurbineInstance /> × N
  │           │   ├── <DroneInstance /> × M
  │           │   └── <FlightPathLines /> × M
  │           ├── <DetailScene>            #   特写 (viewMode === 'detail')
  │           │   ├── <TurbineInstance />  #   聚焦风机 (精渲染)
  │           │   ├── <DroneInstance />    #   关联无人机
  │           │   └── <BladeHighlights />
  │           ├── <CameraManager />
  │           └── <ViewToggle />
  └── <ControlPanel />                     # 侧滑面板 [不动]
```

---

## 4. 数据流

### 4.1 Zustand Store

```typescript
// frontend/src/services/drone3dStore.ts

interface Drone3DState {
  // ── 来自现有 API + DroneSchedulerPage 的数据 ──
  turbines: Turbine[]           // 全量风机数据 (含 lat/lng/region/status/hi_value)
  drones: Drone[]               // 机队状态 (含 path/currentPosition/battery/assignedTurbines)
  activeFarm: string | null     // 当前选中风场 region
  hasPlan: boolean              // 是否已规划路径
  isRunning: boolean            // 仿真是否运行中
  speedMultiplier: number       // 仿真速度倍率

  // ── 3D 视图专属状态 ──
  viewMode: 'overview' | 'detail'
  focusedTurbineId: number | null
  splitRatio: number            // 2D/3D 分屏比例, 默认 0.5

  // ── Actions ──
  setTurbines: (turbines: Turbine[]) => void
  setDrones: (drones: Drone[]) => void
  setActiveFarm: (farm: string | null) => void
  setHasPlan: (v: boolean) => void
  setIsRunning: (v: boolean) => void
  setSpeedMultiplier: (v: number) => void
  focusTurbine: (id: number | null) => void
  setViewMode: (mode: 'overview' | 'detail') => void
  setSplitRatio: (r: number) => void
}
```

### 4.2 数据写入时机

```
DroneSchedulerPage 现有代码:

  api.get('/turbines/')
    .then(data → {
      setTurbines(data.turbines)         // [现有] React state
      drone3dStore.setTurbines(data.turbines)  // 🆕 同步写 store
    })

  planPath(farm, mode, config)
    → buildFleet(result, cfg, farm)
    → setDrones(fleet)                   // [现有] React state
    → drone3dStore.setDrones(fleet)      // 🆕 同步写 store

  tickSimulation()
    → setDrones(newFleet)                // [现有] React state
    → drone3dStore.setDrones(newFleet)   // 🆕 同步写 store (每帧)
```

### 4.3 数据消费

```
2D 视图 (DroneMap):
  props.turbines ← DroneSchedulerPage React state
  props.drones   ← DroneSchedulerPage React state

3D 视图 (WindFarm3DView):
  drone3dStore.turbines  ← zustand selector
  drone3dStore.drones    ← zustand selector
  drone3dStore.viewMode  ← zustand selector
```

**两个视图消费的数据源内容完全一致**，只是通过不同通道（props vs store）获取。DroneSchedulerPage 在每次 setState 时同时写 store，保证 3D 视图拿到最新数据。

---

## 5. 坐标转换

### 5.1 GPS → 3D 场景坐标

```typescript
// frontend/src/utils/coordinateTransform.ts

// 陕西风场中心点 (取 SHAANXI_WIND_BOUNDS 中心)
const ORIGIN_LAT = 37.78
const ORIGIN_LNG = 108.48

const METERS_PER_DEG_LAT = 111_320
const METERS_PER_DEG_LNG = 111_320 * Math.cos(ORIGIN_LAT * Math.PI / 180)
// ≈ 111320 × 0.7907 ≈ 88,025 m/deg

function gpsToScene(lat: number, lng: number, elevation: number = 0): [number, number, number] {
  const z = (lat - ORIGIN_LAT) * METERS_PER_DEG_LAT   // Three.js Z轴 = 北方向
  const x = (lng - ORIGIN_LNG) * METERS_PER_DEG_LNG   // Three.js X轴 = 东方向
  const y = elevation                                   // Three.js Y轴 = 高度
  return [x, y, z]
}
```

**说明**：
- 与现有 `dronePathPlanner.ts` 中的 `haversine()` 公式数学基础一致
- 原点取 `DroneMap.tsx` 中已定义的 `CENTER = [37.78, 108.48]`
- 陕北风场 A/B/C 的 GPS 范围在 30km 以内，平面近似误差 < 0.01%，无需椭球投影
- `elevation` 参数由地形高度函数 + 风机塔筒偏移（80m塔高）组合计算

### 5.2 地形高度采样

风机放置时，从其 `(lat, lng)` 计算出的 `(x, z)` 位置，查询地形高度图：

```typescript
const terrainY = sampleTerrainHeight(x, z)  // 来自 terrainGenerator
const turbineBaseY = terrainY               // 塔筒底部贴地
const turbineTopY = terrainY + 80           // 塔筒高度 80m (2MW风机典型值)
```

无人机飞行高度统一为地形以上 50m（高于风机最高点），确保不会穿模。

---

## 6. 场景设计

### 6.1 地形 (TerrainSurface)

#### 生成参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 平面尺寸 | 800m × 800m | 覆盖单个风场的常见范围 |
| 顶点细分 | 80 × 80 | 6,400 个顶点，每格 10m |
| 噪声算法 | Simplex 3D | `simplex-noise` 包 |
| 基础振幅 | 35m | 黄土高原丘陵起伏 |
| 细节振幅 | 12m | 次级沟壑纹理 |
| 山脊因子 | 0.3 | 模拟侵蚀沟壑 |
| 随机种子 | 固定值 42 | 每次渲染地形一致 |

#### 颜色映射

采用 vertexColors，根据高度 + 坡度混合：

```
低洼处 (y < 10m)   → #8B7355 (深黄土)
坡面   (10-30m)    → #C4A45A (典型黄土)
高处   (30-50m)    → #D4C48C (浅黄褐)
陡坡   (坡度>25°) → #7B8C6E (灰绿, 稀疏灌丛)
```

#### 实现方式

```typescript
// terrainGenerator.ts
import { createNoise2D } from 'simplex-noise'

export function generateHeightmap(width: number, depth: number, segments: number): Float32Array {
  const noise = createNoise2D(() => 42) // 固定种子
  const heights = new Float32Array((segments + 1) * (segments + 1))

  for (let iz = 0; iz <= segments; iz++) {
    for (let ix = 0; ix <= segments; ix++) {
      const worldX = (ix / segments - 0.5) * width
      const worldZ = (iz / segments - 0.5) * depth
      const nx = worldX / width * 3     // 频率缩放
      const nz = worldZ / depth * 3

      let h = noise(nx, nz) * 35        // 基础层
      h += noise(nx * 2.1, nz * 2.1) * 12  // 细节层
      h += Math.abs(noise(nx * 1.5, nz * 1.5)) * 10  // 山脊

      // 边缘衰减
      const edgeFade = smoothEdge(ix, iz, segments)
      h *= edgeFade

      heights[iz * (segments + 1) + ix] = h
    }
  }
  return heights
}
```

地形在 `TerrainSurface.tsx` 中用 `PlaneGeometry` + 手动写入 position buffer 实现。

### 6.2 风机渲染 (TurbineInstance)

#### 加载流程

1. `useGLTF('/models/wind-turbine.glb')` 加载模型
2. 缓存原始 `scene`（所有实例共享同一份 geometry/materials）
3. 每台风机 `clone()` 原始 scene，创建独立实例
4. 定位到 GPS→场景坐标转换的位置（Y 坐标 + 地形高度）

#### 状态映射

| 数据字段 | 视觉效果 | 实现方式 |
|---------|---------|---------|
| `turbine.status === 'fault'` | 塔筒红色描边发光 | `material.emissive = '#ff3333'`, `emissiveIntensity = 0.6` |
| `turbine.status === 'warning'` | 塔筒黄色描边 | `material.emissive = '#ffaa00'`, `emissiveIntensity = 0.4` |
| `turbine.status === 'normal'` | 塔筒默认材质 | 保持 GLTF 原始材质 |
| `turbine.hi_value` | 底座颜色环 | 绿色(≥90) → 黄色(≥70) → 红色(<60) |
| `turbine.power_mw` | 模型缩放 | 2MW→0.85, 3MW→1.0, 5MW→1.15 |

#### 叶片旋转

```typescript
// useFrame 中
const bladesRef = useRef<THREE.Group>(null)

useFrame((_, delta) => {
  if (!bladesRef.current) return
  if (turbine.status === 'fault') return // 故障风机叶片停转
  
  const rpm = turbine.status === 'warning' ? 6 : 12  // 正常 12rpm, 预警降速
  bladesRef.current.rotation.z += (rpm / 60) * Math.PI * 2 * delta
})
```

#### 交互

| 交互 | 触发 | 行为 |
|------|------|------|
| Hover | `onPointerOver` | 塔筒高亮 20% + 显示 `<Html>` 浮窗 |
| Click | `onClick` | `store.focusTurbine(turbine.id)` → 相机飞向该风机 |
| 浮窗内容 | - | 名称 / HI值 / 功率 / 状态 / region |

浮窗使用 drei 的 `<Html>` 组件，渲染标准 React DOM（可复用现有 Tooltip 样式）。

### 6.3 无人机渲染 (DroneInstance)

#### 加载流程

同风机，`useGLTF('/models/drone-quadcopter.glb')` → 缓存 → `clone()` per drone。

#### 实时位置更新

```typescript
useFrame((_, delta) => {
  // 从 store 读取最新 drone 数据（每次 tickSimulation 都会更新）
  const drone = drone3dStore.getState().drones.find(d => d.id === droneId)
  if (!drone || !drone.currentPosition) return

  // GPS → 场景坐标
  const [tx, _, tz] = gpsToScene(drone.currentPosition.lat, drone.currentPosition.lng)
  const ty = sampleTerrainHeight(tx, tz) + 50 // 地形以上 50m

  // 平滑位置 (lerp)
  groupRef.current.position.lerp(new THREE.Vector3(tx, ty, tz), 0.3)

  // 朝向 = 路径切线方向
  if (drone.path.length >= 2 && drone.progress < drone.path.length - 1) {
    const seg = Math.min(Math.floor(drone.progress), drone.path.length - 2)
    const [nx, , nz] = gpsToScene(drone.path[seg + 1].lat, drone.path[seg + 1].lng)
    const [cx, , cz] = gpsToScene(drone.path[seg].lat, drone.path[seg].lng)
    const targetAngle = Math.atan2(nx - cx, nz - cz)
    groupRef.current.rotation.y = lerpAngle(groupRef.current.rotation.y, targetAngle, 0.2)
  }

  // 飞行姿态倾斜 (前倾 5°)
  bodyRef.current.rotation.x = -0.087 // -5° in radians

  // 旋翼旋转 (800rpm)
  propellersRef.current.forEach(p => {
    p.rotation.y += (800 / 60) * Math.PI * 2 * delta
  })
})
```

#### 悬停拍摄效果

当无人机到达分配的风机位置时（`drone.progress` 经过 assignedTurbines 对应的路径点）：

```
- 悬停 2 秒 (减速动画)
- 旋翼转速加大 → 1200rpm
- 机腹下方出现绿色扫描锥 (半透明 ConeGeometry, 0.3 opacity)
- 锥体从机身向下扫描到风机叶片位置
- 完成后锥体消失，速度恢复正常
```

#### 飞行尾迹

已完成路径段：`Line` 实线，颜色=drone.color，width=3
未完成路径段：`LineDashedMaterial`，opacity=0.3

### 6.4 飞行路径线 (FlightPathLines)

从 `drone.path[]` 生成 3D 线段：

```typescript
// 遍历 drone.path，转换每个 GPS 点为 3D 坐标
const points3D = drone.path.map(p => {
  const [x, _, z] = gpsToScene(p.lat, p.lng)
  const y = sampleTerrainHeight(x, z) + 50 // 飞行高度
  return new THREE.Vector3(x, y, z)
})

// 已完成段: 实线
const completedGeometry = new BufferGeometry().setFromPoints(
  points3D.slice(0, Math.floor(drone.progress) + 1)
)
// 未完成段: 虚线
const remainingGeometry = new BufferGeometry().setFromPoints(
  points3D.slice(Math.floor(drone.progress))
)
```

---

## 7. 特写模式 (DetailScene)

### 7.1 进入特写

```
1. 用户在总览点击某台风机 (id=N)
2. store.focusTurbine(N)
3. store.setViewMode('detail')
4. CameraManager 检测到 viewMode 变化
5. 计算目标相机位置: 风机前方 120m, 高度 60m, lookAt 风机中心
6. 使用 lerp + easeInOutCubic 平滑飞行 (0.8s)
7. 飞行期间禁用 OrbitControls
8. 飞行完成后启用受限 OrbitControls (以风机为 orbit 中心)
```

### 7.2 场景内容

- **聚焦风机**：精渲染，其他风机 opacity 0.15
- **关联无人机**：只显示 assignedTurbines 包含该风机的无人机
- **绕飞路径**：3D 螺旋线围绕风机（如果该风机被分配了巡检任务）
- **叶片高亮**：如果存在该风机的 bladeImages 数据，在叶片表面标记脉冲绿点
- **信息浮窗**：固定显示在风机左侧（名称 / HI / 状态 / SCADA 关键值 / 最近故障）

### 7.3 返回总览

```
触发:
  - 双击空白处
  - 点击 ViewToggle 按钮
  - 按 Esc 键 (通过 useEffect keydown listener)

行为:
  - CameraManager 飞行回总览默认视角
  - store.setViewMode('overview')
  - 所有风机恢复默认 opacity
```

---

## 8. 相机控制 (CameraManager)

### 8.1 总览模式

| 操作 | 行为 |
|------|------|
| 左键拖拽 | 绕场景中心旋转 |
| 滚轮 | 缩放 (限制: 不得低于地形面, 不得高于 800m) |
| 中键拖拽 | 平移 |
| 右键拖拽 | 旋转 |

初始视角：相机在原点上方 400m，俯角 45°，面向北偏东 15°（覆盖陕北风场区域）。

### 8.2 特写模式

所有操作以 `focusedTurbine` 的 3D 位置为 orbit 中心点。
缩放范围限制在 30m-300m（可近到看清叶片，远到看完整风机+环境）。

### 8.3 模式切换动画

```typescript
// CameraManager.tsx
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

function animateCameraTransition(
  camera: THREE.PerspectiveCamera,
  controls: any,  // OrbitControls ref
  targetPos: THREE.Vector3,
  targetLookAt: THREE.Vector3,
  duration: number = 0.8,
) {
  const startPos = camera.position.clone()
  const startTarget = controls.target.clone()
  let elapsed = 0

  // 在 useFrame 中每帧调用
  return (delta: number) => {
    elapsed += delta
    const t = Math.min(elapsed / duration, 1)
    const eased = easeInOutCubic(t)

    camera.position.lerpVectors(startPos, targetPos, eased)
    controls.target.lerpVectors(startTarget, targetLookAt, eased)

    return t >= 1 // 返回 true 表示完成
  }
}
```

---

## 9. 环境与光照 (EnvironmentSetup)

### 9.1 光源配置

```typescript
// 方向光 (太阳)
<directionalLight
  position={[0.6, -0.8, 0.4]}  // 方向向量: 下午西南方向
  color="#fff3e0"               // 暖白光
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

// 环境光
<ambientLight color="#4a6c8f" intensity={0.6} />

// 半球光 (天空+地面)
<hemisphereLight
  skyColor="#87CEEB"
  groundColor="#8B7355"
  intensity={0.4}
/>
```

### 9.2 雾

```typescript
<fog
  attach="fog"
  color="#d4c48c"   // 黄土色雾
  near={600}
  far={1400}
/>
```

### 9.3 天空背景

使用 scene.background 设置为渐变色的 Canvas 纹理，或直接用 solid color：

```typescript
// 最简方案
scene.background = new THREE.Color('#7ec8e3')  // 浅蓝天空

// 进阶方案 (可选)
// 用 drei 的 Sky 组件生成物理天空
```

---

## 10. 页面布局改动

### 10.1 DroneSchedulerPage 修改点

**唯一需要修改的现有文件**：`frontend/src/pages/DroneScheduler/DroneSchedulerPage.tsx`

改动内容：
1. 引入 `WindFarm3DView` 组件和 `drone3dStore`
2. 在数据加载/状态更新处加一行 `drone3dStore.setXxx()` 调用
3. 地图区域从单个 `DroneMap` 改为 flex 分屏容器：

```tsx
{/* 原: <div className="flex-1 relative ..."><DroneMap .../></div> */}

{/* 🆕 分屏容器 */}
<div className="flex-1 relative mx-6 mb-3 flex gap-2">
  {/* 左侧: 2D 地图 */}
  <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle">
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

  {/* 右侧: 3D 视图 */}
  <div className="flex-1 rounded-xl overflow-hidden border border-border-subtle">
    <WindFarm3DView />
  </div>
</div>
```

**所有其他现有文件不动。**

### 10.2 分屏比例控制

在分屏容器顶部中间放一个小拖拽手柄，允许用户调整 2D/3D 比例（30%/70% 到 70%/30%）。或者提供三个预设按钮：`[2D全屏] [分屏] [3D全屏]`。

---

## 11. 数据保真度保证

### 11.1 风机数量与位置

- 不硬编码任何风机数量。`turbines.length` 是多少就渲染多少台
- GPS 坐标从 `turbines[].lat/lng` 实时读取 → `gpsToScene()` 转换
- 风场分组从 `turbines[].region` 读取
- 当 `activeFarm` 切换时，3D 视图高亮对应风场的风机（其他半透明），相机飞到该风场上空

### 11.2 无人机机队

- 无人机数量从 `drones.length` 读取
- 路径点从 `drones[].path[]` 读取
- 位置从 `drones[].currentPosition` 读取（tickSimulation 实时计算）
- 颜色从 `drones[].color` 读取
- 分配/完成状态从 `drones[].assignedTurbines/completedTurbines` 读取

### 11.3 数据链路

```
API (FastAPI /api/turbines/)
  → DroneSchedulerPage.tsx (api.get → setTurbines)
  → drone3dStore.setTurbines(turbines)
  → WindFarm3DView → OverviewScene → TurbineInstance × turbines.length
    每个 TurbineInstance 读取 turbine.lat/lng → gpsToScene() → 3D 位置
```

**没有中间硬编码环节**。数据库里改一台风机的坐标/状态，刷新页面后 3D 视图自动反映。

---

## 12. 实现阶段

### Phase 1: 基础骨架 (核心)

**目标**：3D Canvas 显示，地形可见，风机静态摆放

| 任务 | 文件 |
|------|------|
| 安装依赖 | `package.json` (+3 个包) |
| 坐标转换工具 | `utils/coordinateTransform.ts` |
| 地形生成器 | `utils/terrainGenerator.ts` |
| zustand store | `services/drone3dStore.ts` |
| 环境/光照/雾 | `three/EnvironmentSetup.tsx` |
| 地形 mesh | `three/TerrainSurface.tsx` |
| 风机实例 (静态) | `three/TurbineInstance.tsx` |
| 总览场景 | `three/OverviewScene.tsx` |
| 3D 视图入口 | `three/WindFarm3DView.tsx` |
| 分屏布局 | `DroneSchedulerPage.tsx` (改) |

**验证**：打开 DroneScheduler 页面，右侧出现 3D 地形 + 30 台风机在正确位置。

### Phase 2: 状态同步

**目标**：2D 操作驱动 3D 变化

| 任务 | 文件 |
|------|------|
| DroneSchedulerPage 数据写入 store | `DroneSchedulerPage.tsx` |
| 无人机实例 (位置跟随) | `three/DroneInstance.tsx` |
| 飞行路径线 | `three/FlightPathLines.tsx` |
| 相机控制 (OrbitControls) | `three/CameraManager.tsx` |

**验证**：规划路径 → 执行仿真 → 3D 无人机沿路径飞行，与 2D 同步。

### Phase 3: 交互打磨

**目标**：hover/click/view 切换

| 任务 | 文件 |
|------|------|
| 风机 hover 浮窗 | `three/TurbineTooltip.tsx` |
| 风机 click → 特写 | `CameraManager.tsx` 扩展 |
| 特写场景 | `three/DetailScene.tsx` |
| 相机飞行动画 | `CameraManager.tsx` 扩展 |
| 叶片旋转 | `TurbineInstance.tsx` 扩展 |
| 无人机飞行姿态 | `DroneInstance.tsx` 扩展 |
| ViewToggle 按钮 | `three/ViewToggle.tsx` |

**验证**：hover 看浮窗，click 切特写，相机飞行流畅，叶片旋转自然。

### Phase 4: 视觉效果

**目标**：答辩级别的视觉品质

| 任务 | 文件 |
|------|------|
| 旋翼旋转动画 | `DroneInstance.tsx` 扩展 |
| 悬停拍摄锥体效果 | `DroneInstance.tsx` 扩展 |
| 飞行尾迹渐变 | `FlightPathLines.tsx` 扩展 |
| 叶片损伤脉冲标记 | `three/BladeHighlights.tsx` |
| 风机状态发光 | `TurbineInstance.tsx` 扩展 |
| 地形颜色优化 | `TerrainSurface.tsx` 扩展 |

### Phase 5: 性能与健壮

| 任务 |
|------|
| 模型加载失败 fallback（显示简单几何体代替） |
| 大屏/小屏自适应分屏比例 |
| 内存清理（组件卸载时 dispose geometry/materials） |
| 60fps 性能验证（Chrome DevTools FPS meter） |

---

## 13. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| GLTF 模型节点结构不匹配 | 中 | 下载后先用 `scene.traverse(console.log)` 打印节点树，写健壮的 `getObjectByName` + fallback 递归查找 |
| Sketchfab 模型需要登录才能下载 | 中 | 备选模型 + 如果都失败，用 Three.js 基础几何体拼一个简化无人机（圆柱机身 + 4 个 Box 旋翼臂） |
| simplex-noise 与 Vite SSR 冲突 | 低 | `simplex-noise` 纯 JS，无 Node 依赖，Vite 直接打包 |
| 30 台风机 3D 渲染性能不足 | 低 | 总面数 ~50K，任何设备都能跑 60fps；如需优化用 `InstancedMesh` |
| 坐标转换精度不足导致风机位置偏移 | 低 | 平面近似在 30km 范围内误差 < 3m，视觉上不可感知 |

---

## 14. 验收标准

- [ ] 页面打开，右侧出现 3D 场景，地形可见，光照正常
- [ ] 风机按数据库中实际数量和 GPS 坐标摆放，位置准确
- [ ] 风机颜色反映实际 status（正常/预警/故障）
- [ ] 选择风场后，3D 视图聚焦对应区域
- [ ] 规划路径后，3D 中出现无人机和飞行路径线
- [ ] 执行仿真后，无人机沿路径飞行，与 2D 同步
- [ ] hover 风机显示信息浮窗
- [ ] click 风机进入特写模式，相机飞行流畅
- [ ] 特写模式叶片旋转，无人机绕飞可见
- [ ] 返回总览按钮正常工作
- [ ] 60fps 稳定运行（不掉帧）
- [ ] 模型加载失败时有 fallback，不白屏

---

## 附录 A: 模型下载步骤

### 风机模型

1. 访问 https://www.cgtrader.com/free-3d-models/industrial/other/low-poly-wind-turbine-free
2. 点击 "Download Free"（可能需要注册 CGTrader 账号）
3. 选择 glTF 格式下载
4. 解压，将 `.gltf` + `.bin` + 纹理文件放入 `frontend/public/models/`
5. 如有 `.glb` 格式更佳（单文件，无需分离纹理）

### 无人机模型

1. 访问 https://sketchfab.com/3d-models/low-poly-quadcopter-drone-fa0261d9db004dda9d4d3ff9bc985717
2. 点击 "Download 3D Model"（需要 Sketchfab 账号，免费注册）
3. 选择 "glTF Binary (.glb)" 格式
4. 将 `.glb` 文件放入 `frontend/public/models/drone-quadcopter.glb`

### 备选：程序化风机

如果无法下载模型，用 Three.js 基础几何体拼装风机：

```
Tower:  CylinderGeometry(radiusTop=2, radiusBottom=3, height=80, segments=8)
Nacelle: BoxGeometry(width=8, height=4, depth=4)
Hub:    SphereGeometry(radius=1.5, segments=8)
Blade:  BoxGeometry(width=0.5, height=30, depth=1.5) × 3, 旋转 120° 均布
```

约 200 面/台，性能更佳，但视觉不如 GLTF 模型。作为最终 fallback。

---

## 附录 B: 参考资源

- [react-three-fiber 文档](https://docs.pmnd.rs/react-three-fiber)
- [drei 文档](https://github.com/pmndrs/drei)
- [Three.js 文档](https://threejs.org/docs/)
- [simplex-noise npm](https://www.npmjs.com/package/simplex-noise)
- [Three.js 程序化地形教程](https://threejs-journey.com/)
- 项目内参考: `dronePathPlanner.ts` (haversine 距离计算), `DroneMap.tsx` (GPS 坐标使用)
