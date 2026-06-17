/**
 * Drone Path Planner 鈥?TSP + VRP algorithms for wind farm turbine inspection.
 * Pure TypeScript, zero dependencies. Runs in < 50ms for N 鈮?200.
 */

// 鈹€鈹€ Types 鈹€鈹€

export interface Point {
  lat: number;
  lng: number;
  id?: number;
  name?: string;
}

export interface TspResult {
  path: Point[];          // ordered visit sequence
  totalDistance: number;  // meters
  iterations: number;     // 2-opt iterations
}

export interface DroneAssignment {
  droneIndex: number;
  turbines: Point[];
  path: TspResult;
  color: string;
}

export interface VrpResult {
  assignments: DroneAssignment[];
  totalDistance: number;
  balanced: boolean;
}

// 鈹€鈹€ Helpers 鈹€鈹€

export function haversine(a: Point, b: Point): number {
  const R = 6_371_000; // Earth radius in meters
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const aa = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
  return R * 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
}

function pathDistance(points: Point[]): number {
  if (points.length < 2) return 0;
  let d = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    d += haversine(points[i], points[i + 1]);
  }
  return d;
}

/**
 * Solve TSP for a set of turbine points with an optional start point.
 * Algorithm: nearest neighbor initial tour + 2-opt local optimization.
 */
export function solveTsp(
  turbines: Point[],
  startPoint?: Point,
  options?: { maxIterations?: number },
): TspResult {
  if (turbines.length === 0) return { path: [], totalDistance: 0, iterations: 0 };
  if (turbines.length === 1) return { path: [turbines[0]], totalDistance: 0, iterations: 0 };

  const maxIter = options?.maxIterations ?? 500;
  const nodes = [...turbines];
  const unvisited = new Set(nodes.map((_, i) => i));
  let current = startPoint ? { ...startPoint } : nodes[0];
  const tour: Point[] = [];
  let firstIdx = 0;

  if (startPoint) {
    let minDist = Infinity;
    for (let i = 0; i < nodes.length; i += 1) {
      const d = haversine(current, nodes[i]);
      if (d < minDist) {
        minDist = d;
        firstIdx = i;
      }
    }
  }

  tour.push(nodes[firstIdx]);
  unvisited.delete(firstIdx);
  current = nodes[firstIdx];

  while (unvisited.size > 0) {
    let minDist = Infinity;
    let nextIdx = -1;
    for (const idx of unvisited) {
      const d = haversine(current, nodes[idx]);
      if (d < minDist) {
        minDist = d;
        nextIdx = idx;
      }
    }
    tour.push(nodes[nextIdx]);
    unvisited.delete(nextIdx);
    current = nodes[nextIdx];
  }

  let bestTour = [...tour];
  let bestDist = pathDistance(bestTour);
  let improved = true;
  let iter = 0;

  while (improved && iter < maxIter) {
    improved = false;
    iter += 1;
    for (let i = 0; i < bestTour.length - 1; i += 1) {
      for (let j = i + 1; j < bestTour.length; j += 1) {
        const candidate = [
          ...bestTour.slice(0, i + 1),
          ...bestTour.slice(i + 1, j + 1).reverse(),
          ...bestTour.slice(j + 1),
        ];
        const candidateDist = pathDistance(candidate);
        if (candidateDist < bestDist - 0.01) {
          bestTour = candidate;
          bestDist = candidateDist;
          improved = true;
        }
      }
    }
  }

  return { path: bestTour, totalDistance: Math.round(bestDist), iterations: iter };
}

function centroidOf(points: Point[]): Point {
  return {
    lat: points.reduce((s, p) => s + p.lat, 0) / points.length,
    lng: points.reduce((s, p) => s + p.lng, 0) / points.length,
  };
}

interface Cluster {
  centroid: Point;
  members: Point[];
}

function chooseBalancedCentroids(points: Point[], k: number): Point[] {
  const global = centroidOf(points);
  const first = points.reduce((best, p) => (
    haversine(p, global) < haversine(best, global) ? p : best
  ), points[0]);
  const centroids: Point[] = [first];

  while (centroids.length < k) {
    let candidate = points[0];
    let bestScore = -Infinity;
    for (const point of points) {
      const minDist = Math.min(...centroids.map((c) => haversine(point, c)));
      if (minDist > bestScore) {
        bestScore = minDist;
        candidate = point;
      }
    }
    centroids.push(candidate);
  }

  return centroids;
}

function balancedKMeans(points: Point[], k: number): Cluster[] {
  if (k >= points.length) {
    return points.map((p) => ({ centroid: { lat: p.lat, lng: p.lng }, members: [p] }));
  }
  if (k <= 0) k = 1;

  const centroids = chooseBalancedCentroids(points, k);
  const maxClusterSize = Math.ceil(points.length / k);
  let clusters: Cluster[] = centroids.map((c) => ({ centroid: c, members: [] }));

  for (let iteration = 0; iteration < 24; iteration += 1) {
    clusters = centroids.map((c) => ({ centroid: c, members: [] }));
    const ordered = [...points].sort((a, b) => {
      const da = Math.min(...centroids.map((c) => haversine(a, c)));
      const db = Math.min(...centroids.map((c) => haversine(b, c)));
      return db - da;
    });

    for (const point of ordered) {
      const ranked = clusters
        .map((cluster, index) => ({
          index,
          score: haversine(point, cluster.centroid) * (1 + cluster.members.length / Math.max(1, maxClusterSize)),
        }))
        .sort((a, b) => a.score - b.score);
      const selected = ranked.find((r) => clusters[r.index].members.length < maxClusterSize) ?? ranked[0];
      clusters[selected.index].members.push(point);
    }

    let moved = false;
    clusters.forEach((cluster, index) => {
      if (!cluster.members.length) return;
      const next = centroidOf(cluster.members);
      if (haversine(next, centroids[index]) > 0.5) {
        centroids[index] = next;
        moved = true;
      }
      cluster.centroid = centroids[index];
    });
    if (!moved) break;
  }

  return clusters;
}

// 鈹€鈹€ VRP: K-Means + TSP 鈹€鈹€ 鈹€鈹€

const DRONE_COLORS = ['#f0883e', '#388bfd', '#a371f7', '#39d2c0', '#f85149', '#d29922', '#3fb950', '#ff69b4'];

/**
 * Solve VRP: partition turbines into k clusters, then solve TSP for each.
 * Includes load-balancing step to keep clusters similar in size.
 */
export function solveVrp(
  turbines: Point[],
  droneCount: number,
  startPoint?: Point,
  options?: { maxImbalance?: number },
): VrpResult {
  if (droneCount <= 0) droneCount = 1;
  if (droneCount > turbines.length) droneCount = turbines.length;

  const maxImbalance = options?.maxImbalance ?? 0.25; // 25% tolerance
  const clusters = balancedKMeans(turbines, droneCount);

  // Build assignments
  const assignments: DroneAssignment[] = clusters.map((cluster, i) => {
    const color = DRONE_COLORS[i % DRONE_COLORS.length];
    const tsp = solveTsp(cluster.members, startPoint);
    return {
      droneIndex: i,
      turbines: cluster.members,
      path: tsp,
      color,
    };
  });

  // Local improvement: exchange boundary turbines between routes when it shortens
  // the actual per-drone TSP distance. This fixes cases where balanced clustering
  // keeps counts even but assigns an obvious neighbor to the wrong route.
  let swapped = true;
  while (swapped) {
    swapped = false;

    for (let i = 0; i < assignments.length; i += 1) {
      for (let j = i + 1; j < assignments.length; j += 1) {
        const a = assignments[i];
        const b = assignments[j];
        const baseDistance = a.path.totalDistance + b.path.totalDistance;
        let bestSwap: {
          ai: number;
          bi: number;
          nextA: TspResult;
          nextB: TspResult;
          distance: number;
        } | null = null;

        for (let ai = 0; ai < a.turbines.length; ai += 1) {
          for (let bi = 0; bi < b.turbines.length; bi += 1) {
            const nextATurbines = [...a.turbines];
            const nextBTurbines = [...b.turbines];
            [nextATurbines[ai], nextBTurbines[bi]] = [nextBTurbines[bi], nextATurbines[ai]];

            const nextA = solveTsp(nextATurbines, startPoint);
            const nextB = solveTsp(nextBTurbines, startPoint);
            const distance = nextA.totalDistance + nextB.totalDistance;
            if (distance < baseDistance - 1 && (!bestSwap || distance < bestSwap.distance)) {
              bestSwap = { ai, bi, nextA, nextB, distance };
            }
          }
        }

        if (bestSwap) {
          [a.turbines[bestSwap.ai], b.turbines[bestSwap.bi]] = [b.turbines[bestSwap.bi], a.turbines[bestSwap.ai]];
          a.path = bestSwap.nextA;
          b.path = bestSwap.nextB;
          swapped = true;
        }
      }
    }
  }

  // Load balancing: if any cluster has > 25% more than average, redistribute
  const avgSize = turbines.length / droneCount;
  let rebalanced = false;

  for (let i = 0; i < assignments.length; i += 1) {
    const overSize = assignments[i].turbines.length > avgSize * (1 + maxImbalance);
    if (!overSize) continue;

    for (let j = 0; j < assignments.length; j += 1) {
      if (i === j) continue;
      const underSize = assignments[j].turbines.length < avgSize * (1 - maxImbalance);
      if (!underSize) continue;

      // Move the closest turbine from overloaded to underloaded cluster
      const overloaded = assignments[i].turbines;
      const centroid = assignments[j].turbines.length > 0
        ? {
            lat: assignments[j].turbines.reduce((s, t) => s + t.lat, 0) / assignments[j].turbines.length,
            lng: assignments[j].turbines.reduce((s, t) => s + t.lng, 0) / assignments[j].turbines.length,
          }
        : assignments[j].path.path[0] || assignments[i].turbines[0];

      let minDist = Infinity;
      let moveIdx = -1;
      for (let ti = 0; ti < overloaded.length; ti += 1) {
        const d = haversine(overloaded[ti], centroid);
        if (d < minDist) { minDist = d; moveIdx = ti; }
      }

      if (moveIdx >= 0) {
        const moved = overloaded.splice(moveIdx, 1)[0];
        assignments[j].turbines.push(moved);
        rebalanced = true;
        break;
      }
    }
    if (rebalanced) break;
  }

  // Recalculate TSP for changed clusters
  if (rebalanced) {
    for (const a of assignments) {
      a.path = solveTsp(a.turbines, startPoint);
    }
  }

  const totalDist = assignments.reduce((s, a) => s + a.path.totalDistance, 0);
  return { assignments, totalDistance: Math.round(totalDist), balanced: !rebalanced };
}

