import { useEffect, useMemo, useRef } from 'react';
import type { MutableRefObject } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { useDrone3DStore } from '../../../services/drone3dStore';
import { gpsToScene } from '../../../utils/coordinateTransform';
import type { Drone, InspectionTargetPart, InspectionWaypoint, Turbine } from '../../../types';

function routePositionFromPoints(points: THREE.Vector3[], progress: number) {
  const path = points;
  if (path.length === 0) return null;
  if (path.length === 1) return path[0].clone();
  const seg = Math.min(Math.floor(progress), path.length - 2);
  const frac = Math.max(0, Math.min(progress - seg, 1));
  const a = path[seg];
  const b = path[seg + 1];
  return a.clone().lerp(b, frac);
}

function partOffset(part: InspectionTargetPart) {
  const offsets: Record<InspectionTargetPart, [number, number, number]> = {
    blade_tip: [2, 115, 0],
    blade_root: [2, 86, 0],
    leading_edge: [2, 104, -8],
    trailing_edge: [2, 104, 8],
    hub: [2, 82, 0],
    nacelle: [-3, 84, 0],
  };
  return new THREE.Vector3(...offsets[part]);
}

function nearestTarget(drone: Drone, turbines: Turbine[], position: THREE.Vector3, part: InspectionTargetPart) {
  const assigned = turbines.filter((t) => drone.assignedTurbines.includes(t.id));
  if (assigned.length === 0) return position.clone().add(new THREE.Vector3(30, 0, 0));

  let bestTarget: THREE.Vector3 | null = null;
  let bestDistance = Infinity;
  for (const turbine of assigned) {
    const [x, , z] = gpsToScene(turbine.lat, turbine.lng, 0);
    const target = new THREE.Vector3(x, 0, z).add(partOffset(part));
    const distance = target.distanceToSquared(position);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestTarget = target;
    }
  }
  return bestTarget ?? position.clone().add(new THREE.Vector3(30, 0, 0));
}

function buildRoutePoints(drone: Drone, _waypoints: InspectionWaypoint[], altitude: number) {
  return drone.path.map((p) => {
    const pointAltitude = p.alt ?? altitude;
    const [x, , z] = gpsToScene(p.lat, p.lng, pointAltitude);
    return new THREE.Vector3(x, pointAltitude, z);
  });
}

function clampPitch(value: number) {
  const limit = Math.PI / 2 - 0.08;
  return Math.max(-limit, Math.min(limit, value));
}

function lookDirection(yaw: number, pitch: number) {
  return new THREE.Vector3(
    Math.sin(yaw) * Math.cos(pitch),
    Math.sin(pitch),
    Math.cos(yaw) * Math.cos(pitch),
  ).normalize();
}

function firstInspectionPoint(drone: Drone) {
  return drone.path.find((p) => p.kind === 'inspect') ?? drone.path[1] ?? drone.path[0];
}

function takeoffCameraPose(drone: Drone | undefined) {
  if (!drone || drone.path.length === 0) {
    return {
      position: new THREE.Vector3(0, 420, 360),
      target: new THREE.Vector3(0, 0, 0),
    };
  }

  const takeoff = drone.path[0];
  const targetPoint = firstInspectionPoint(drone);
  const takeoffAlt = takeoff.alt ?? 8;
  const [tx, , tz] = gpsToScene(takeoff.lat, takeoff.lng, takeoffAlt);
  const [ix, , iz] = gpsToScene(targetPoint.lat, targetPoint.lng, targetPoint.alt ?? drone._altitude ?? 90);
  const origin = new THREE.Vector3(tx, takeoffAlt, tz);
  const target = new THREE.Vector3(ix, targetPoint.alt ?? drone._altitude ?? 90, iz);
  const direction = new THREE.Vector3().subVectors(target, origin);
  direction.y = 0;
  if (direction.lengthSq() < 1) direction.set(0, 0, -1);
  direction.normalize();
  const side = new THREE.Vector3(-direction.z, 0, direction.x).multiplyScalar(60);
  const position = origin.clone()
    .sub(direction.multiplyScalar(150))
    .add(side)
    .add(new THREE.Vector3(0, 92, 0));

  return { position, target };
}

function applyLookAtPose(
  camera: THREE.Camera,
  positionRef: MutableRefObject<THREE.Vector3>,
  yawRef: MutableRefObject<number>,
  pitchRef: MutableRefObject<number>,
  position: THREE.Vector3,
  target: THREE.Vector3,
) {
  positionRef.current.copy(position);
  camera.position.copy(position);
  const toTarget = new THREE.Vector3().subVectors(target, position).normalize();
  yawRef.current = Math.atan2(toTarget.x, toTarget.z);
  pitchRef.current = clampPitch(Math.asin(toTarget.y));
}

export default function CameraManager() {
  const { camera, gl } = useThree();
  const keysRef = useRef(new Set<string>());
  const rotatingRef = useRef(false);
  const yawRef = useRef(-Math.PI);
  const pitchRef = useRef(-0.72);
  const cameraPosRef = useRef(new THREE.Vector3(0, 420, 360));
  const lastModeRef = useRef<string | null>(null);
  const lastFollowPosRef = useRef<THREE.Vector3 | null>(null);

  const drones = useDrone3DStore((s) => s.drones);
  const turbines = useDrone3DStore((s) => s.turbines);
  const activeFarm = useDrone3DStore((s) => s.activeFarm);
  const cameraMode = useDrone3DStore((s) => s.cameraMode);
  const part = useDrone3DStore((s) => s.inspectionTargetPart);
  const inspectionWaypoints = useDrone3DStore((s) => s.inspectionWaypoints);
  const selectedDroneId = useDrone3DStore((s) => s.selectedDroneId);

  const visibleTurbines = useMemo(
    () => activeFarm ? turbines.filter((t) => t.region === activeFarm) : turbines,
    [activeFarm, turbines],
  );

  const selectedDrone = drones.find((d) => d.id === selectedDroneId) ?? drones[0];
  const primaryDrone = drones.find((d) => d.status === 'flying' && (!selectedDroneId || d.id === selectedDroneId))
    || drones.find((d) => d.status === 'flying')
    || selectedDrone;

  useEffect(() => {
    if (cameraMode !== 'overview') return;
    const pose = takeoffCameraPose(selectedDrone);
    applyLookAtPose(camera, cameraPosRef, yawRef, pitchRef, pose.position, pose.target);
    lastFollowPosRef.current = null;
  }, [camera, cameraMode, selectedDroneId, selectedDrone?.path]);

  useEffect(() => {
    const canvas = gl.domElement;

    const keyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        useDrone3DStore.getState().setCameraMode('overview');
        return;
      }
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'w', 'a', 's', 'd', 'q', 'e', 'shift', 'W', 'A', 'S', 'D', 'Q', 'E', 'Shift'].includes(e.key)) {
        keysRef.current.add(e.key.toLowerCase());
        e.preventDefault();
      }
    };
    const keyUp = (e: KeyboardEvent) => keysRef.current.delete(e.key.toLowerCase());
    const pointerDown = (e: PointerEvent) => {
      if (e.button !== 2 || useDrone3DStore.getState().cameraMode === 'fpv') return;
      rotatingRef.current = true;
      canvas.setPointerCapture(e.pointerId);
      e.preventDefault();
    };
    const pointerMove = (e: PointerEvent) => {
      if (!rotatingRef.current || useDrone3DStore.getState().cameraMode === 'fpv') return;
      yawRef.current -= e.movementX * 0.005;
      pitchRef.current = clampPitch(pitchRef.current - e.movementY * 0.004);
    };
    const pointerUp = (e: PointerEvent) => {
      rotatingRef.current = false;
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    };
    const wheel = (e: WheelEvent) => {
      if (useDrone3DStore.getState().cameraMode === 'fpv') return;
      const dir = lookDirection(yawRef.current, pitchRef.current);
      const step = THREE.MathUtils.clamp(Math.abs(e.deltaY) * 0.18, 8, 80);
      cameraPosRef.current.add(dir.multiplyScalar(e.deltaY < 0 ? step : -step));
      e.preventDefault();
    };
    const contextMenu = (e: MouseEvent) => e.preventDefault();

    window.addEventListener('keydown', keyDown);
    window.addEventListener('keyup', keyUp);
    canvas.addEventListener('pointerdown', pointerDown);
    canvas.addEventListener('pointermove', pointerMove);
    canvas.addEventListener('pointerup', pointerUp);
    canvas.addEventListener('pointerleave', pointerUp);
    canvas.addEventListener('wheel', wheel, { passive: false });
    canvas.addEventListener('contextmenu', contextMenu);
    return () => {
      window.removeEventListener('keydown', keyDown);
      window.removeEventListener('keyup', keyUp);
      canvas.removeEventListener('pointerdown', pointerDown);
      canvas.removeEventListener('pointermove', pointerMove);
      canvas.removeEventListener('pointerup', pointerUp);
      canvas.removeEventListener('pointerleave', pointerUp);
      canvas.removeEventListener('wheel', wheel);
      canvas.removeEventListener('contextmenu', contextMenu);
    };
  }, [gl.domElement]);

  useFrame((_, delta) => {
    if (lastModeRef.current !== cameraMode) {
      lastModeRef.current = cameraMode;
      lastFollowPosRef.current = null;

      if (cameraMode === 'overview') {
        const pose = takeoffCameraPose(selectedDrone);
        applyLookAtPose(camera, cameraPosRef, yawRef, pitchRef, pose.position, pose.target);
      }

      if (cameraMode === 'follow' && primaryDrone) {
        const route = buildRoutePoints(primaryDrone, inspectionWaypoints, primaryDrone._altitude ?? 70);
        const pos = routePositionFromPoints(route, primaryDrone.progress);
        if (pos) {
          cameraPosRef.current.copy(pos).add(new THREE.Vector3(-85, 54, 85));
          camera.position.copy(cameraPosRef.current);
          lastFollowPosRef.current = pos.clone();
          const toDrone = new THREE.Vector3().subVectors(pos, cameraPosRef.current).normalize();
          yawRef.current = Math.atan2(toDrone.x, toDrone.z);
          pitchRef.current = -0.35;
        }
      }
    }

    if (cameraMode === 'follow' && primaryDrone) {
      const route = buildRoutePoints(primaryDrone, inspectionWaypoints, primaryDrone._altitude ?? 70);
      const dronePos = routePositionFromPoints(route, primaryDrone.progress);
      if (dronePos) {
        if (lastFollowPosRef.current) {
          cameraPosRef.current.add(new THREE.Vector3().subVectors(dronePos, lastFollowPosRef.current));
        }
        lastFollowPosRef.current = dronePos.clone();
      }
    }

    if (cameraMode === 'overview' || cameraMode === 'follow') {
      const dir = lookDirection(yawRef.current, pitchRef.current);
      const flatForward = dir.clone();
      flatForward.y = 0;
      flatForward.normalize();
      const right = new THREE.Vector3().crossVectors(flatForward, camera.up).normalize();
      const move = new THREE.Vector3();
      const keys = keysRef.current;
      if (keys.has('arrowup') || keys.has('w')) move.add(flatForward);
      if (keys.has('arrowdown') || keys.has('s')) move.sub(flatForward);
      if (keys.has('arrowleft') || keys.has('a')) move.sub(right);
      if (keys.has('arrowright') || keys.has('d')) move.add(right);
      if (keys.has('q')) move.y -= 1;
      if (keys.has('e')) move.y += 1;
      const moveSpeed = keys.has('shift') ? 420 : 220;
      if (move.lengthSq() > 0) cameraPosRef.current.add(move.normalize().multiplyScalar(moveSpeed * delta));

      camera.position.lerp(cameraPosRef.current, 0.32);
      camera.lookAt(camera.position.clone().add(dir));
      return;
    }

    if (!primaryDrone) return;
    const route = buildRoutePoints(primaryDrone, inspectionWaypoints, primaryDrone._altitude ?? 70);
    const dronePos = routePositionFromPoints(route, primaryDrone.progress);
    if (!dronePos) return;
    const target = nearestTarget(primaryDrone, visibleTurbines, dronePos, part);
    const heading = new THREE.Vector3().subVectors(target, dronePos).normalize();

    const desired = dronePos.clone()
      .add(new THREE.Vector3(0, 2.2, 0))
      .add(heading.clone().multiplyScalar(4));
    camera.position.lerp(desired, 0.24);
    camera.lookAt(target);
  });

  return null;
}
