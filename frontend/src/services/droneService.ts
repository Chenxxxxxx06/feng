/**
 * 无人机巡检后端服务封装 — 对接 backend/app/api/drone.py（挂载于 /api/drone）。
 *
 * 数据披露说明（评审可核查）：
 * 前端 3D 巡检为仿真演示，没有真实机载相机。上传给后端的图像是由本地 Canvas
 * 渲染的「3D 数字孪生仿真帧」，帧内烧录了 SIMULATED 字样，落库时统一标注
 * data_source='sim_3d_render'。质量门 / 缺陷检测 / 证据 / 事件全部由后端真实计算并入库，
 * 前端只展示后端返回的原始结果，不做任何本地伪造。
 */

import api from './api';

const BASE = '/drone';

// ── 前端部位 → 后端巡检角度（backend REQUIRED_ANGLES 只覆盖叶片五视角，
//    轮毂/机舱等部位后端无对应枚举，按原名上报，missing-angles 会如实反映缺口）──
export const PART_TO_ANGLE: Record<string, string> = {
  blade_tip: 'tip_view',
  blade_root: 'blade_root',
  leading_edge: 'leading_edge',
  trailing_edge: 'trailing_edge',
  hub: 'hub',
  nacelle: 'nacelle',
};

// ── Schemas（字段与 backend/app/api/drone.py 一一对应）──

export interface DroneWaypointPayload {
  lat: number;
  lng: number;
  alt: number;
  angle?: string;
  part?: string;
  seq?: number;
}

export interface MissionCreateBody {
  turbine_id: number;
  component?: string;
  waypoints?: DroneWaypointPayload[];
  drone_id?: string;
  pilot?: string;
}

export interface MissionCreated {
  id: number;
  mission_id: string;
  turbine_id: number;
  turbine_name: string;
  component: string;
  status: string;
  waypoints: DroneWaypointPayload[];
  created_at: string;
}

export interface MissionSummary {
  id: number;
  mission_id: string;
  turbine_id: number;
  component: string;
  status: string;
  total_shots: number | null;
  passed_shots: number | null;
  failed_shots: number | null;
  created_at: string;
}

export interface MissionImage {
  id: number;
  component: string | null;
  angle: string | null;
  waypoint_index: number | null;
  gps_lat: number | null;
  gps_lng: number | null;
  image_path: string | null;
  quality_passed: boolean | null;
  retake_requested: boolean | null;
  retake_reason: string | null;
  algorithm_mode: string | null;
  diagnosis_type: string | null;
  diagnosis_confidence: number | null;
  evidence_id: number | null;
  captured_at: string | null;
}

export interface MissionDetail {
  mission_id: string;
  turbine_id: number;
  turbine_name: string;
  component: string;
  status: string;
  waypoints: DroneWaypointPayload[];
  total_shots: number | null;
  passed_shots: number | null;
  failed_shots: number | null;
  incident_id: number | null;
  images: MissionImage[];
}

export interface CaptureParams {
  turbine_id: number;
  component?: string;
  angle?: string;
  waypoint_index?: number;
  gps_lat?: number;
  gps_lng?: number;
  altitude_m?: number;
  shoot_distance_m?: number;
  algorithm_mode?: string;
  model_version?: string;
  data_source?: string;
  data_license?: string;
}

export interface CaptureResult {
  id: number;
  mission_id: string;
  image_path: string;
  angle: string | null;
  waypoint_index: number | null;
  captured_at: string;
}

export interface QualityResult {
  image_id: number;
  passed: boolean;
  blur_score: number | null;
  exposure_ok: boolean | null;
  issues: string[];
  retake_reason: string | null;
  retake_requested: boolean | null;
}

export interface DetectedDefect {
  type?: string;
  confidence?: number;
  bbox?: number[];
  severity?: string;
  source?: string;
  area_px?: number;
}

export interface DetectResult {
  image_id: number;
  /** real_inference = 真实模型推理；demo_fixture = 演示样例数据（非真实检测） */
  algorithm_mode: string;
  model_version: string | null;
  diagnosis_type: string | null;
  diagnosis_confidence: number | null;
  damage_bbox: number[] | null;
  defects_detected: DetectedDefect[];
  data_source: string | null;
}

export interface EvidenceLinkResult {
  evidence_id: number;
  node_type?: string;
  label?: string;
  confidence?: number;
  image_id: number;
  already_linked: boolean;
}

export interface MissionIncidentResult {
  incident_id: string;
  mission_id: string;
  turbine_name?: string;
  has_defect?: boolean;
  evidence_linked?: number;
  next_action?: string;
  already_exists?: boolean;
}

export interface MissingAnglesResult {
  mission_id: string;
  required_angles: string[];
  captured_angles: string[];
  missing_angles: string[];
  retakes_needed: number;
  evidence_complete: boolean;
  recommendation: string;
}

// ── Endpoints ──

export async function createMission(body: MissionCreateBody): Promise<MissionCreated> {
  const { data } = await api.post(`${BASE}/missions`, body);
  return data;
}

export async function fetchMissions(params?: {
  turbine_id?: number;
  status?: string;
}): Promise<MissionSummary[]> {
  const { data } = await api.get(`${BASE}/missions`, { params });
  return Array.isArray(data) ? data : [];
}

export async function fetchMission(missionId: string): Promise<MissionDetail> {
  const { data } = await api.get(`${BASE}/missions/${missionId}`);
  return data;
}

/** status: planned / in_flight / completed / aborted（后端以 query 参数接收） */
export async function updateMissionStatus(
  missionId: string,
  status: string,
): Promise<{ mission_id: string; status: string }> {
  const { data } = await api.put(`${BASE}/missions/${missionId}/status`, null, {
    params: { status },
  });
  return data;
}

/** 上传一帧巡检图像。后端为 multipart 文件字段 image + 其余字段走 query。 */
export async function captureImage(
  missionId: string,
  frame: File,
  params: CaptureParams,
): Promise<CaptureResult> {
  const form = new FormData();
  form.append('image', frame, frame.name);
  const { data } = await api.post(`${BASE}/missions/${missionId}/capture`, form, {
    params,
    timeout: 30_000,
  });
  return data;
}

export async function checkImageQuality(imageId: number): Promise<QualityResult> {
  const { data } = await api.post(`${BASE}/images/${imageId}/quality-check`);
  return data;
}

export async function detectDefects(imageId: number): Promise<DetectResult> {
  const { data } = await api.post(`${BASE}/images/${imageId}/detect`, null, {
    timeout: 60_000,
  });
  return data;
}

export async function linkEvidence(
  imageId: number,
  incidentId?: number,
): Promise<EvidenceLinkResult> {
  const { data } = await api.post(`${BASE}/images/${imageId}/link-evidence`, null, {
    params: incidentId ? { incident_id: incidentId } : undefined,
  });
  return data;
}

export async function createIncidentFromMission(
  missionId: string,
): Promise<MissionIncidentResult> {
  const { data } = await api.post(`${BASE}/missions/${missionId}/create-incident`);
  return data;
}

export async function fetchMissingAngles(missionId: string): Promise<MissingAnglesResult> {
  const { data } = await api.get(`${BASE}/missions/${missionId}/missing-angles`);
  return data;
}

// ── 错误处理 ──

export function describeDroneError(err: unknown): string {
  const e = err as {
    response?: { status?: number; data?: { detail?: unknown } };
    message?: string;
    code?: string;
  };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (e?.response?.status === 403) return '当前账号权限不足（缺陷检测/证据需要 engineer 及以上角色）';
  if (e?.response?.status) return `HTTP ${e.response.status}`;
  if (e?.code === 'ECONNABORTED') return '请求超时';
  return e?.message || '未知错误';
}

/** 判断是否属于"后端不可达"类错误 —— 触发前端降级为离线演示 */
export function isOfflineError(err: unknown): boolean {
  const e = err as { response?: { status?: number }; code?: string };
  if (!e?.response) return true;
  const status = e.response.status ?? 0;
  return status >= 500 || status === 0;
}

// ── 仿真帧生成（本地 Canvas，帧内烧录 SIMULATED 标识）──

export interface SimulatedFrameMeta {
  missionId: string;
  turbineName: string;
  partLabel: string;
  angle: string;
  seq: number;
  total: number;
  altitudeM: number;
  yawDeg: number;
  pitchDeg: number;
  shootDistanceM: number;
  /** true = 人工注入的低质量帧，用于演示后端补拍门禁 */
  degraded?: boolean;
}

const FRAME_WIDTH = 1280;
const FRAME_HEIGHT = 960;

function drawTurbineSilhouette(ctx: CanvasRenderingContext2D) {
  const hubX = FRAME_WIDTH * 0.5;
  const hubY = FRAME_HEIGHT * 0.36;

  // 塔筒
  ctx.fillStyle = '#e6ebef';
  ctx.beginPath();
  ctx.moveTo(hubX - 16, hubY);
  ctx.lineTo(hubX + 16, hubY);
  ctx.lineTo(hubX + 34, FRAME_HEIGHT * 0.86);
  ctx.lineTo(hubX - 34, FRAME_HEIGHT * 0.86);
  ctx.closePath();
  ctx.fill();

  // 塔筒法兰环（高频结构，供拉普拉斯清晰度评估）
  ctx.strokeStyle = '#9aa7b1';
  ctx.lineWidth = 2;
  for (let i = 1; i < 12; i += 1) {
    const y = hubY + ((FRAME_HEIGHT * 0.86 - hubY) * i) / 12;
    const half = 16 + (34 - 16) * (i / 12);
    ctx.beginPath();
    ctx.moveTo(hubX - half, y);
    ctx.lineTo(hubX + half, y);
    ctx.stroke();
  }

  // 机舱
  ctx.fillStyle = '#f2f5f7';
  ctx.fillRect(hubX - 26, hubY - 26, 96, 46);
  ctx.strokeStyle = '#8b98a3';
  ctx.strokeRect(hubX - 26, hubY - 26, 96, 46);

  // 叶片
  ctx.save();
  ctx.translate(hubX, hubY);
  for (let i = 0; i < 3; i += 1) {
    ctx.rotate((Math.PI * 2) / 3);
    ctx.fillStyle = '#eef2f5';
    ctx.beginPath();
    ctx.moveTo(-10, 0);
    ctx.quadraticCurveTo(40, -190, 10, -330);
    ctx.quadraticCurveTo(-6, -190, -10, 0);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = '#96a4af';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  ctx.restore();

  // 轮毂
  ctx.fillStyle = '#dde4ea';
  ctx.beginPath();
  ctx.arc(hubX, hubY, 22, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#8b98a3';
  ctx.stroke();
}

function drawSensorNoise(ctx: CanvasRenderingContext2D, amplitude: number) {
  const frame = ctx.getImageData(0, 0, FRAME_WIDTH, FRAME_HEIGHT);
  const d = frame.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * amplitude;
    d[i] += n;
    d[i + 1] += n;
    d[i + 2] += n;
  }
  ctx.putImageData(frame, 0, 0);
}

function drawDisclosureHud(ctx: CanvasRenderingContext2D, meta: SimulatedFrameMeta) {
  ctx.fillStyle = 'rgba(6, 14, 26, 0.72)';
  ctx.fillRect(0, 0, FRAME_WIDTH, 74);
  ctx.fillRect(0, FRAME_HEIGHT - 96, FRAME_WIDTH, 96);

  ctx.fillStyle = '#ffd166';
  ctx.font = 'bold 26px "Segoe UI", sans-serif';
  ctx.fillText('SIMULATED FRAME · 3D数字孪生仿真帧 · 非真实航拍照片', 24, 46);

  ctx.fillStyle = '#d7e3f0';
  ctx.font = '20px "Segoe UI", monospace';
  ctx.fillText(
    `${meta.missionId} | ${meta.turbineName} | ${meta.partLabel} (${meta.angle}) | 航点 ${meta.seq}/${meta.total}`,
    24,
    FRAME_HEIGHT - 60,
  );
  ctx.fillText(
    `ALT ${meta.altitudeM.toFixed(1)}m | YAW ${meta.yawDeg}° | PITCH ${meta.pitchDeg}° | DIST ${meta.shootDistanceM}m | ${new Date().toISOString()}`,
    24,
    FRAME_HEIGHT - 28,
  );
}

/**
 * 渲染一帧仿真巡检图像并封装为 File（jpeg）。
 * degraded=true 时人工做模糊+压暗处理，用于验证后端质量门与补拍机制。
 */
export async function buildSimulatedFrame(meta: SimulatedFrameMeta): Promise<File> {
  if (typeof document === 'undefined') throw new Error('当前环境不支持 Canvas 取帧');
  const canvas = document.createElement('canvas');
  canvas.width = FRAME_WIDTH;
  canvas.height = FRAME_HEIGHT;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D 上下文不可用');

  const sky = ctx.createLinearGradient(0, 0, 0, FRAME_HEIGHT);
  sky.addColorStop(0, '#5d93c4');
  sky.addColorStop(0.62, '#b9d2e6');
  sky.addColorStop(1, '#cfdcc2');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT);

  ctx.fillStyle = '#6d8a58';
  ctx.fillRect(0, FRAME_HEIGHT * 0.84, FRAME_WIDTH, FRAME_HEIGHT * 0.16);

  drawTurbineSilhouette(ctx);
  drawSensorNoise(ctx, meta.degraded ? 10 : 30);
  drawDisclosureHud(ctx, meta);

  if (meta.degraded) {
    ctx.filter = 'blur(8px)';
    ctx.drawImage(canvas, 0, 0);
    ctx.filter = 'none';
    ctx.fillStyle = 'rgba(0, 0, 0, 0.88)';
    ctx.fillRect(0, 0, FRAME_WIDTH, FRAME_HEIGHT);
    ctx.fillStyle = '#ff6b6b';
    ctx.font = 'bold 22px "Segoe UI", sans-serif';
    ctx.fillText('DEGRADED TEST FRAME · 人工注入低质量帧（用于验证补拍门禁）', 24, 40);
  }

  const blob = await new Promise<Blob | null>((resolve) => {
    canvas.toBlob(resolve, 'image/jpeg', 0.86);
  });
  if (!blob) throw new Error('仿真帧编码失败');

  const name = `sim_${meta.missionId}_${meta.angle}_${meta.seq}.jpg`;
  return new File([blob], name, { type: 'image/jpeg' });
}
