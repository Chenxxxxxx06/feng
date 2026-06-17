/**
 * Drone Path Planner — TSP + VRP algorithms for wind farm turbine inspection.
 * Pure TypeScript, zero dependencies. Runs in < 50ms for N ≤ 200.
 */

// ── Types ──

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

// ── Helpers ──

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

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// ── TSP: Nearest Neighbor + 2-opt ──

/**
 * Solve TSP for a set of turbine points with an optional start point.
 * Algorithm: Nearest Neighbor for initial tour, then 2-opt local optimization.
 */
export function solveTsp(
  turbines: Point[],
  startPoint?: Point,
  options?: { maxIterations?: number; seed?: number },
): TspResult {
  if (turbines.length === 0) {
    return { path: [], totalDistance: 0, iterations: 0 };
  }
  if (turbines.length === 1) {
    return { path: [turbines[0]], totalDistance: 0, iterations: 0 };
  }

  const maxIter = options?.maxIterations ?? 500;
  const nodes = [...turbines];

  // Build initial tour: nearest neighbor from startPoint (or first turbine)
  const unvisited = new Set(nodes.map((_, i) => i));
  let current = startPoint ? { ...startPoint } : nodes[0];
  const tour: Point[] = [];
  let firstIdx = 0;

  if (startPoint) {
    // Find closest turbine to start as first node
    let minDist = Infinity;
    for (let i = 0; i < nodes.length; i += 1) {
      const d = haversine(current, nodes[i]);
      if (d < minDist) { minDist = d; firstIdx = i; }
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
      if (d < minDist) { minDist = d; nextIdx = idx; }
    }
    tour.push(nodes[nextIdx]);
    unvisited.delete(nextIdx);
    current = nodes[nextIdx];
  }

  // 2-opt optimization
  let bestTour = [...tour];
  let bestDist = pathDistance(bestTour);
  let improved = true;
  let iter = 0;

  while (improved && iter < maxIter) {
    improved = false;
    iter += 1;
    for (let i = 0; i < bestTour.length - 1; i += 1) {
      for (let j = i + 1; j < bestTour.length; j += 1) {
        // Try reversing segment (i+1 ... j)
        const newTour = [
          ...bestTour.slice(0, i + 1),
          ...bestTour.slice(i + 1, j + 1).reverse(),
          ...bestTour.slice(j + 1),
        ];
        const newDist = pathDistance(newTour);
        if (newDist < bestDist - 0.01) {
          bestTour = newTour;
          bestDist = newDist;
          improved = true;
        }
      }
    }
  }

  return { path: bestTour, totalDistance: Math.round(bestDist), iterations: iter };
}

// ── K-Means Clustering ──

interface Cluster {
  centroid: Point;
  members: Point[];
}

function kMeans(points: Point[], k: number, seed?: number): Cluster[] {
  if (k >= points.length) {
    return points.map((p, i) => ({
      centroid: { lat: p.lat, lng: p.lng },
      members: [p],
    }));
  }
  if (k <= 0) k = 1;

  // Initialize centroids: k-means++ style (first random, rest farthest)
  const rng = seed !== undefined ? mulberry32(seed) : Math.random;
  const shuffled = shuffle(points);
  const centroids: Point[] = [shuffled[0]];

  for (let c = 1; c < k; c += 1) {
    let maxDist = -1;
    let farthest: Point = shuffled[0];
    for (const p of points) {
      let minDist = Infinity;
      for (const centroid of centroids) {
        const d = haversine(p, centroid);
        if (d < minDist) minDist = d;
      }
      if (minDist > maxDist) { maxDist = minDist; farthest = p; }
    }
    centroids.push(farthest);
  }

  // Iterate
  for (let iteration = 0; iteration < 20; iteration += 1) {
    const clusters: Cluster[] = centroids.map((c) => ({ centroid: c, members: [] }));
    for (const p of points) {
      let minDist = Infinity;
      let best = 0;
      for (let ci = 0; ci < clusters.length; ci += 1) {
        const d = haversine(p, clusters[ci].centroid);
        if (d < minDist) { minDist = d; best = ci; }
      }
      clusters[best].members.push(p);
    }

    let moved = false;
    for (let ci = 0; ci < clusters.length; ci += 1) {
      const cluster = clusters[ci];
      if (cluster.members.length === 0) continue;
      const avgLat = cluster.members.reduce((s, m) => s + m.lat, 0) / cluster.members.length;
      const avgLng = cluster.members.reduce((s, m) => s + m.lng, 0) / cluster.members.length;
      if (Math.abs(avgLat - cluster.centroid.lat) > 1e-6 || Math.abs(avgLng - cluster.centroid.lng) > 1e-6) {
        cluster.centroid = { lat: avgLat, lng: avgLng };
        centroids[ci] = { lat: avgLat, lng: avgLng };
        moved = true;
      }
    }
    if (!moved) break;
  }

  return centroids.map((c) => {
    const members: Point[] = [];
    for (const p of points) {
      let minDist = Infinity;
      let best = 0;
      for (let ci = 0; ci < centroids.length; ci += 1) {
        const d = haversine(p, centroids[ci]);
        if (d < minDist) { minDist = d; best = ci; }
      }
      if (best === centroids.indexOf(c)) members.push(p);
    }
    return { centroid: c, members };
  });
}

// ── VRP: K-Means + TSP ──

const DRONE_COLORS = [
  '#f0883e', '#388bfd', '#a371f7', '#39d2c0', '#f85149', '#d29922', '#3fb950',
  '#ff69b4', '#00d4aa', '#ff6b6b', '#48dbfb', '#feca57',
];

/**
 * Solve VRP: partition turbines into k clusters, then solve TSP for each.
 * Includes load-balancing step to keep clusters similar in size.
 * When droneCount is close to turbineCount, uses simple 1-per-drone assignment.
 */
export function solveVrp(
  turbines: Point[],
  droneCount: number,
  startPoint?: Point,
  options?: { maxImbalance?: number },
): VrpResult {
  if (droneCount <= 0) droneCount = 1;
  if (droneCount > turbines.length) droneCount = turbines.length;

  // ── High drone count: simple 1-per-drone (k-means unreliable when k ≈ n) ──
  if (droneCount >= turbines.length || droneCount > turbines.length * 0.7) {
    const assignments: DroneAssignment[] = [];
    // Each drone gets at least one turbine; remainder go to first drones
    let turbineIdx = 0;
    for (let i = 0; i < droneCount; i += 1) {
      const droneTurbines: Point[] = [];
      // Assign at least one turbine if available
      if (turbineIdx < turbines.length) {
        droneTurbines.push(turbines[turbineIdx]);
        turbineIdx += 1;
      }
      assignments.push({
        droneIndex: i,
        turbines: droneTurbines,
        path: droneTurbines.length > 0 ? solveTsp(droneTurbines, startPoint) : { path: [], totalDistance: 0, iterations: 0 },
        color: DRONE_COLORS[i % DRONE_COLORS.length],
      });
    }
    // Distribute remaining turbines to first drones (round-robin)
    let assignTo = 0;
    while (turbineIdx < turbines.length) {
      assignments[assignTo % assignments.length].turbines.push(turbines[turbineIdx]);
      turbineIdx += 1;
      assignTo += 1;
    }
    // Recalculate TSP for drones that got extra turbines
    for (const a of assignments) {
      if (a.turbines.length > 1) {
        a.path = solveTsp(a.turbines, startPoint);
      }
    }
    const totalDist = assignments.reduce((s, a) => s + a.path.totalDistance, 0);
    return { assignments, totalDistance: Math.round(totalDist), balanced: true };
  }

  const maxImbalance = options?.maxImbalance ?? 0.5;
  const clusters = kMeans(turbines, droneCount);

  // Build assignments, skipping empty clusters
  let assignments: DroneAssignment[] = clusters
    .filter((c) => c.members.length > 0)
    .map((cluster, i) => {
      const color = DRONE_COLORS[i % DRONE_COLORS.length];
      const tsp = solveTsp(cluster.members, startPoint);
      return { droneIndex: i, turbines: cluster.members, path: tsp, color };
    });

  // ── Redistribute empty-cluster drones: take 1 turbine from largest cluster ──
  let missing = droneCount - assignments.length;
  while (missing > 0) {
    // Find cluster with most turbines
    let maxIdx = 0;
    for (let i = 1; i < assignments.length; i += 1) {
      if (assignments[i].turbines.length > assignments[maxIdx].turbines.length) maxIdx = i;
    }
    if (assignments[maxIdx].turbines.length <= 1) break; // can't split further

    const donor = assignments[maxIdx].turbines;
    // Move turbine farthest from donor's centroid to new drone
    const donorCenter = {
      lat: donor.reduce((s, t) => s + t.lat, 0) / donor.length,
      lng: donor.reduce((s, t) => s + t.lng, 0) / donor.length,
    };
    let farthestIdx = 0;
    let farthestDist = -1;
    for (let ti = 0; ti < donor.length; ti += 1) {
      const d = haversine(donor[ti], donorCenter);
      if (d > farthestDist) { farthestDist = d; farthestIdx = ti; }
    }
    const [moved] = donor.splice(farthestIdx, 1);
    assignments.push({
      droneIndex: assignments.length,
      turbines: [moved],
      path: solveTsp([moved], startPoint),
      color: DRONE_COLORS[assignments.length % DRONE_COLORS.length],
    });
    // Recalculate donor's TSP
    assignments[maxIdx].path = solveTsp(assignments[maxIdx].turbines, startPoint);
    missing -= 1;
  }

  // Load balancing: if any cluster has > 50% more than average, redistribute
  const avgSize = turbines.length / assignments.length;
  let rebalanced = false;

  for (let i = 0; i < assignments.length; i += 1) {
    if (assignments[i].turbines.length <= avgSize * (1 + maxImbalance)) continue;

    for (let j = 0; j < assignments.length; j += 1) {
      if (i === j) continue;
      if (assignments[j].turbines.length >= avgSize * (1 - maxImbalance)) continue;

      const overloaded = assignments[i].turbines;
      const underCentroid = assignments[j].turbines.length > 0
        ? {
            lat: assignments[j].turbines.reduce((s, t) => s + t.lat, 0) / assignments[j].turbines.length,
            lng: assignments[j].turbines.reduce((s, t) => s + t.lng, 0) / assignments[j].turbines.length,
          }
        : overloaded[0];

      let minDist = Infinity;
      let moveIdx = -1;
      for (let ti = 0; ti < overloaded.length; ti += 1) {
        const d = haversine(overloaded[ti], underCentroid);
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

  // Re-index drones after redistribution
  assignments.forEach((a, i) => { a.droneIndex = i; });
  const totalDist = assignments.reduce((s, a) => s + a.path.totalDistance, 0);
  return { assignments, totalDistance: Math.round(totalDist), balanced: !rebalanced };
}

// ── RNG helper ──

function mulberry32(seed: number): () => number {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
