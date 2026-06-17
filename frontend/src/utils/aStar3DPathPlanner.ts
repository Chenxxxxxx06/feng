/**
 * AStar3DPathPlanner.ts — 3D A* Pathfinding for UAV/Drone Flight Planning
 * 基于 AeroMind (https://github.com/Zguoxu/AeroMind) 移植为 TypeScript
 *
 * 特性:
 * - 3D A* with 26-direction search
 * - 禁飞区 (No-Fly Zone) 规避
 * - 可配置网格分辨率
 * - 路径平滑
 * - 起飞/降落斜坡路径生成
 *
 * Reference:
 * - A* Algorithm (Hart, Nilsson, Raphael, 1968)
 * - 3D pathfinding for aerial robotics
 */

// ── Types ──

export interface Waypoint3D {
  lat: number;
  lng: number;
  altitude: number;
}

export interface NoFlyZone {
  name: string;
  south_lat: number;
  north_lat: number;
  west_lng: number;
  east_lng: number;
  min_altitude: number;
  max_altitude: number;
}

export interface AStarOptions {
  gridResolution?: number;
  maxIterations?: number;
  smoothPath?: boolean;
  cruiseAltitude?: number;
}

export interface PathStatistics {
  totalWaypoints: number;
  totalDistance: number;
  totalTime: number;
  totalTimeMinutes: number;
  maxAltitude: number;
  minAltitude: number;
  averageSpeed: number;
}

export interface PlanResult {
  success: boolean;
  path: Waypoint3D[];
  statistics?: PathStatistics;
  error?: string;
}

// ── Grid Node ──

class GridNode {
  x: number;
  y: number;
  z: number;
  lat: number;
  lng: number;
  altitude: number;
  g = 0;
  h = 0;
  f = 0;
  parent: GridNode | null = null;
  walkable = true;

  constructor(x: number, y: number, z: number, lat: number, lng: number, altitude: number) {
    this.x = x;
    this.y = y;
    this.z = z;
    this.lat = lat;
    this.lng = lng;
    this.altitude = altitude;
  }

  updateF(): void {
    this.f = this.g + this.h;
  }
}

// ── Priority Queue ──

class PriorityQueue {
  items: GridNode[] = [];

  enqueue(node: GridNode): void {
    if (this.items.length === 0) {
      this.items.push(node);
    } else {
      let added = false;
      for (let i = 0; i < this.items.length; i++) {
        if (node.f < this.items[i].f) {
          this.items.splice(i, 0, node);
          added = true;
          break;
        }
      }
      if (!added) this.items.push(node);
    }
  }

  dequeue(): GridNode | undefined {
    return this.items.shift();
  }

  isEmpty(): boolean {
    return this.items.length === 0;
  }

  contains(node: GridNode): boolean {
    return this.items.some(
      (item) => item.x === node.x && item.y === node.y && item.z === node.z,
    );
  }
}

// ── Grid Info ──

interface GridInfo {
  minLat: number; maxLat: number;
  minLng: number; maxLng: number;
  minAlt: number; maxAlt: number;
  gridX: number; gridY: number; gridZ: number;
}

// ── AStar3DPathPlanner ──

export class AStar3DPathPlanner {
  gridResolution: number;
  maxIterations: number;
  noFlyZones: NoFlyZone[] = [];

  constructor(options: { gridResolution?: number; maxIterations?: number } = {}) {
    this.gridResolution = options.gridResolution || 100;
    this.maxIterations = options.maxIterations || 50000;
  }

  setNoFlyZones(zones: NoFlyZone[]): void {
    this.noFlyZones = zones;
  }

  /** 主体: 规划3D路径 */
  planPath(start: Waypoint3D, end: Waypoint3D, options: AStarOptions = {}): PlanResult {
    try {
      const gridData = this.create3DGrid(start, end, options);
      if (!gridData) throw new Error('Failed to create 3D grid');

      const { grid, startNode, endNode, gridInfo } = gridData;
      this.markNoFlyZones(grid, gridInfo);

      const path = this.findPathAStar(grid, startNode, endNode);
      if (!path || path.length === 0) throw new Error('No path found');

      const waypoints: Waypoint3D[] = path.map((node) => ({
        lat: node.lat,
        lng: node.lng,
        altitude: node.altitude,
      }));

      const smoothedPath = options.smoothPath ? this.smoothPath(waypoints) : waypoints;
      const statistics = this.calculateStatistics(smoothedPath);

      return { success: true, path: smoothedPath, statistics };
    } catch (error: any) {
      return { success: false, error: error.message, path: [] };
    }
  }

  /**
   * 规划完整飞行路径: 起飞爬升 → 巡航(A*) → 降落
   */
  planFullFlightPath(
    start: Waypoint3D,
    end: Waypoint3D,
    cruiseAltitude: number,
    options: AStarOptions = {},
  ): PlanResult {
    // Start and end from ground
    const groundStart = { ...start, altitude: 0 };
    const groundEnd = { ...end, altitude: 0 };
    const cruiseStart = { ...start, altitude: cruiseAltitude };
    const cruiseEnd = { ...end, altitude: cruiseAltitude };

    // Phase 1: Takeoff
    const takeoffPath = this.planTakeoffPath(groundStart, cruiseAltitude, cruiseEnd);

    // Phase 2: Cruise (A* at altitude)
    const cruiseResult = this.planPath(cruiseStart, cruiseEnd, options);
    const cruisePath = cruiseResult.success ? cruiseResult.path : [cruiseStart, cruiseEnd];

    // Phase 3: Landing
    const landingPath = this.planLandingPath(
      cruisePath[cruisePath.length - 1],
      groundEnd,
      cruiseAltitude,
    );

    const fullPath = [...takeoffPath, ...cruisePath, ...landingPath];
    const statistics = this.calculateStatistics(fullPath);

    return { success: true, path: fullPath, statistics };
  }

  // ── Internal ──

  private create3DGrid(
    start: Waypoint3D, end: Waypoint3D, options: AStarOptions,
  ): { grid: GridNode[][][]; startNode: GridNode; endNode: GridNode; gridInfo: GridInfo } | null {
    const gridResolution = options.gridResolution || this.gridResolution;

    const minLat = Math.min(start.lat, end.lat) - 0.01;
    const maxLat = Math.max(start.lat, end.lat) + 0.01;
    const minLng = Math.min(start.lng, end.lng) - 0.01;
    const maxLng = Math.max(start.lng, end.lng) + 0.01;
    const minAlt = Math.min(start.altitude, end.altitude) - 20;
    const maxAlt = Math.max(start.altitude, end.altitude) + 100;

    const latRange = maxLat - minLat;
    const lngRange = maxLng - minLng;
    const altRange = maxAlt - minAlt;

    const latMeters = latRange * 111_320;
    const lngMeters = lngRange * 111_320 * Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const altMeters = altRange;

    const gridX = Math.max(3, Math.ceil(lngMeters / gridResolution));
    const gridY = Math.max(3, Math.ceil(latMeters / gridResolution));
    const gridZ = Math.max(3, Math.ceil(altMeters / gridResolution));

    // Create 3D grid
    const grid: GridNode[][][] = [];
    for (let x = 0; x < gridX; x++) {
      grid[x] = [];
      for (let y = 0; y < gridY; y++) {
        grid[x][y] = [];
        for (let z = 0; z < gridZ; z++) {
          const lat = minLat + (y / gridY) * latRange;
          const lng = minLng + (x / gridX) * lngRange;
          const altitude = minAlt + (z / gridZ) * altRange;
          grid[x][y][z] = new GridNode(x, y, z, lat, lng, altitude);
        }
      }
    }

    const gridInfo: GridInfo = { minLat, maxLat, minLng, maxLng, minAlt, maxAlt, gridX, gridY, gridZ };

    const startNode = this.getGridNode(grid, start.lat, start.lng, start.altitude, gridInfo);
    const endNode = this.getGridNode(grid, end.lat, end.lng, end.altitude, gridInfo);

    if (!startNode.walkable || !endNode.walkable) return null;

    return { grid, startNode, endNode, gridInfo };
  }

  private getGridNode(
    grid: GridNode[][][], lat: number, lng: number, alt: number, info: GridInfo,
  ): GridNode {
    const x = Math.floor(((lng - info.minLng) / (info.maxLng - info.minLng)) * info.gridX);
    const y = Math.floor(((lat - info.minLat) / (info.maxLat - info.minLat)) * info.gridY);
    const z = Math.floor(((alt - info.minAlt) / (info.maxAlt - info.minAlt)) * info.gridZ);

    const cx = Math.max(0, Math.min(info.gridX - 1, x));
    const cy = Math.max(0, Math.min(info.gridY - 1, y));
    const cz = Math.max(0, Math.min(info.gridZ - 1, z));

    return grid[cx][cy][cz];
  }

  private markNoFlyZones(grid: GridNode[][][], info: GridInfo): void {
    if (!this.noFlyZones.length) return;

    for (let x = 0; x < info.gridX; x++) {
      for (let y = 0; y < info.gridY; y++) {
        for (let z = 0; z < info.gridZ; z++) {
          const node = grid[x][y][z];
          for (const zone of this.noFlyZones) {
            if (this.isPointInZone(node.lat, node.lng, node.altitude, zone)) {
              node.walkable = false;
              break;
            }
          }
        }
      }
    }
  }

  private isPointInZone(lat: number, lng: number, altitude: number, zone: NoFlyZone): boolean {
    const inLat = lat >= zone.south_lat && lat <= zone.north_lat;
    const inLng = lng >= zone.west_lng && lng <= zone.east_lng;
    const inAlt = altitude >= zone.min_altitude && altitude <= zone.max_altitude;
    return inLat && inLng && inAlt;
  }

  private findPathAStar(
    grid: GridNode[][][], startNode: GridNode, endNode: GridNode,
  ): GridNode[] | null {
    const openList = new PriorityQueue();
    const closedList: GridNode[] = [];

    startNode.g = 0;
    startNode.h = this.heuristic(startNode, endNode);
    startNode.updateF();
    openList.enqueue(startNode);

    let iterations = 0;
    let closestNode = startNode;
    let closestDistance = startNode.h;

    while (!openList.isEmpty() && iterations < this.maxIterations) {
      iterations++;
      const currentNode = openList.dequeue()!;

      if (currentNode.x === endNode.x && currentNode.y === endNode.y && currentNode.z === endNode.z) {
        return this.reconstructPath(currentNode);
      }

      closedList.push(currentNode);

      const distToEnd = this.heuristic(currentNode, endNode);
      if (distToEnd < closestDistance) {
        closestDistance = distToEnd;
        closestNode = currentNode;
      }

      const neighbors = this.getNeighbors(grid, currentNode);
      for (const neighbor of neighbors) {
        if (!neighbor.walkable || closedList.some(
          (n) => n.x === neighbor.x && n.y === neighbor.y && n.z === neighbor.z,
        )) continue;

        const tentativeG = currentNode.g + this.distance(currentNode, neighbor);
        const inOpenList = openList.contains(neighbor);

        if (!inOpenList || tentativeG < neighbor.g) {
          neighbor.parent = currentNode;
          neighbor.g = tentativeG;
          neighbor.h = this.heuristic(neighbor, endNode);
          neighbor.updateF();
          if (!inOpenList) openList.enqueue(neighbor);
        }
      }
    }

    if (closestDistance < startNode.h) {
      return this.reconstructPath(closestNode);
    }
    return null;
  }

  private heuristic(a: GridNode, b: GridNode): number {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = b.z - a.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  private distance(a: GridNode, b: GridNode): number {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = b.z - a.z;
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  private getNeighbors(grid: GridNode[][][], node: GridNode): GridNode[] {
    const neighbors: GridNode[] = [];
    const { x, y, z } = node;

    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dz = -1; dz <= 1; dz++) {
          if (dx === 0 && dy === 0 && dz === 0) continue;
          const nx = x + dx, ny = y + dy, nz = z + dz;
          if (nx >= 0 && nx < grid.length &&
              ny >= 0 && ny < grid[0].length &&
              nz >= 0 && nz < grid[0][0].length) {
            neighbors.push(grid[nx][ny][nz]);
          }
        }
      }
    }
    return neighbors;
  }

  private reconstructPath(endNode: GridNode): GridNode[] {
    const path: GridNode[] = [];
    let current: GridNode | null = endNode;
    while (current) {
      path.unshift(current);
      current = current.parent;
    }
    return path;
  }

  // ── Path Smoothing ──

  private smoothPath(waypoints: Waypoint3D[], windowSize = 3): Waypoint3D[] {
    if (waypoints.length < 3) return waypoints;
    const smoothed: Waypoint3D[] = [];

    for (let i = 0; i < waypoints.length; i++) {
      if (i === 0 || i === waypoints.length - 1) {
        smoothed.push(waypoints[i]);
      } else {
        const start = Math.max(0, i - Math.floor(windowSize / 2));
        const end = Math.min(waypoints.length, i + Math.ceil(windowSize / 2));
        const window = waypoints.slice(start, end);
        const avgLat = window.reduce((s, p) => s + p.lat, 0) / window.length;
        const avgLng = window.reduce((s, p) => s + p.lng, 0) / window.length;
        const avgAlt = window.reduce((s, p) => s + p.altitude, 0) / window.length;
        smoothed.push({ lat: avgLat, lng: avgLng, altitude: avgAlt });
      }
    }
    return smoothed;
  }

  // ── Takeoff / Landing ──

  /**
   * 起飞路径: 地面 → 巡航高度 (带坡度)
   * 参考 AeroMind standalone.html planTakeoffPath
   */
  planTakeoffPath(
    start: Waypoint3D,
    cruiseAltitude: number,
    nextPoint: Waypoint3D,
    steps = 10,
  ): Waypoint3D[] {
    const takeoffAngle = 45; // 度
    const climbAngleRad = (takeoffAngle * Math.PI) / 180;
    const horizontalDistance = cruiseAltitude / Math.tan(climbAngleRad);
    const bearing = this.calculateBearing(start.lat, start.lng, nextPoint.lat, nextPoint.lng);
    const latOffset = (horizontalDistance / 111_000) * Math.cos(bearing);
    const lngOffset = (horizontalDistance / 111_000) * Math.sin(bearing);

    const waypoints: Waypoint3D[] = [];
    for (let i = 0; i <= steps; i++) {
      const ratio = i / steps;
      waypoints.push({
        lat: start.lat + latOffset * ratio,
        lng: start.lng + lngOffset * ratio,
        altitude: cruiseAltitude * ratio,
      });
    }
    return waypoints;
  }

  /**
   * 降落路径: 巡航高度 → 地面 (带坡度)
   * 参考 AeroMind standalone.html planLandingPath
   */
  planLandingPath(
    cruiseEnd: Waypoint3D,
    finalEnd: Waypoint3D,
    cruiseAltitude: number,
    steps = 10,
  ): Waypoint3D[] {
    const landingAngle = 30;
    const descentAngleRad = (landingAngle * Math.PI) / 180;
    const horizontalDistance = cruiseAltitude / Math.tan(descentAngleRad);
    const bearing = this.calculateBearing(cruiseEnd.lat, cruiseEnd.lng, finalEnd.lat, finalEnd.lng);
    const latOffset = -(horizontalDistance / 111_000) * Math.cos(bearing);
    const lngOffset = -(horizontalDistance / 111_000) * Math.sin(bearing);

    const landingStartLat = finalEnd.lat + latOffset;
    const landingStartLng = finalEnd.lng + lngOffset;

    const waypoints: Waypoint3D[] = [];
    for (let i = 0; i <= steps; i++) {
      const ratio = i / steps;
      waypoints.push({
        lat: landingStartLat + (finalEnd.lat - landingStartLat) * ratio,
        lng: landingStartLng + (finalEnd.lng - landingStartLng) * ratio,
        altitude: cruiseAltitude * (1 - ratio),
      });
    }
    return waypoints;
  }

  // ── Helpers ──

  private calculateBearing(lat1: number, lng1: number, lat2: number, lng2: number): number {
    const lat1Rad = (lat1 * Math.PI) / 180;
    const lat2Rad = (lat2 * Math.PI) / 180;
    const dLng = ((lng2 - lng1) * Math.PI) / 180;
    const y = Math.sin(dLng) * Math.cos(lat2Rad);
    const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
              Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLng);
    return Math.atan2(y, x);
  }

  /** 计算两点3D距离 (Haversine + 高度差) */
  calculate3DDistance(p1: Waypoint3D, p2: Waypoint3D): number {
    const R = 6_371_000;
    const dLat = ((p2.lat - p1.lat) * Math.PI) / 180;
    const dLng = ((p2.lng - p1.lng) * Math.PI) / 180;
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos((p1.lat * Math.PI) / 180) *
              Math.cos((p2.lat * Math.PI) / 180) *
              Math.sin(dLng / 2) ** 2;
    const horizontalDist = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    const verticalDist = Math.abs(p2.altitude - p1.altitude);
    return Math.sqrt(horizontalDist ** 2 + verticalDist ** 2);
  }

  private calculateStatistics(waypoints: Waypoint3D[]): PathStatistics {
    let totalDistance = 0, totalTime = 0, maxAltitude = 0, minAltitude = Infinity;
    const cruiseSpeed = 15; // m/s

    for (let i = 0; i < waypoints.length - 1; i++) {
      const segDist = this.calculate3DDistance(waypoints[i], waypoints[i + 1]);
      totalDistance += segDist;
      totalTime += segDist / cruiseSpeed;
      maxAltitude = Math.max(maxAltitude, waypoints[i].altitude);
      minAltitude = Math.min(minAltitude, waypoints[i].altitude);
    }

    return {
      totalWaypoints: waypoints.length,
      totalDistance: Math.round(totalDistance),
      totalTime: Math.round(totalTime),
      totalTimeMinutes: Math.round((totalTime / 60) * 10) / 10,
      maxAltitude: Math.round(maxAltitude),
      minAltitude: Math.round(minAltitude),
      averageSpeed: Math.round((totalDistance / totalTime) * 10) / 10,
    };
  }
}
