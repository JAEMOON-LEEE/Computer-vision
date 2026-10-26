import { CALIBRATION, type CameraCalibration } from "./calibration";
import { splitPlace } from "./mapModel";
import { riskLevel } from "./risk";
import type { AlertItem, Camera, Detection, LatestFrame, OverlayState } from "./types";

export type { RiskLevel } from "./risk";
export { riskLevel };

export type TwinObject = {
  trackId: number | null;
  className: string;
  lat: number;
  lon: number;
  riskScore: number;
  note?: string;
  isDemo: boolean;
};

export type RiskEvent = {
  id: number;
  cameraId: string;
  type: string;
  message: string;
  timeMs: number;
  riskScore: number;
  status: string;
  /** 점수가 검출 값이 아니라 심각도에서 환산됐으면 true. */
  isDemo: boolean;
};

export type HeatPoint = { lat: number; lon: number; weight: number; isDemo: boolean };

export type RepeatedSegment = {
  rank: number;
  name: string;
  detail: string;
  count: number;
  lat: number;
  lon: number;
  isDemo: boolean;
};

export type HourBucket = { hour: number; count: number };
export type TypeCount = { type: string; count: number };

const CLASS_SCORE: Record<string, number> = {
  person: 30,
  pothole: 55,
  debris: 55,
};

const DEMO_CLASSES = ["car", "person", "pothole", "debris", "truck", "bus"] as const;
const DEMO_NOTES = ["차선 변경", "횡단 대기", "노면 파임", "낙하물", "저속 주행", "정차"];

/** VITE_DEMO_TWIN=1일 때만 예시 좌표를 만든다. */
export function demoTwinEnabled(): boolean {
  return import.meta.env.VITE_DEMO_TWIN === "1";
}

export function classLabel(className: string): string {
  const labels: Record<string, string> = {
    person: "보행자",
    car: "차량",
    truck: "화물차",
    bus: "버스",
    motorcycle: "이륜차",
    bicycle: "자전거",
    pothole: "포트홀",
    crack: "균열",
    debris: "낙하물",
    barrier: "방호벽",
  };
  return labels[className] ?? className;
}

export function markerShape(className: string): "circle" | "square" | "diamond" {
  if (className === "person") return "square";
  if (className === "pothole" || className === "debris") return "diamond";
  return "circle";
}

/** local_enu. x는 동쪽(m), z는 북쪽(m)이라 회전 없이 원점 위경도에 더한다. */
export function xzToLatLon(
  originLat: number,
  originLon: number,
  x: number,
  z: number,
): { lat: number; lon: number } {
  const east = x;
  const north = z;
  const lat = originLat + north / 111320;
  const lon = originLon + east / (111320 * Math.cos((originLat * Math.PI) / 180));
  return { lat, lon };
}

function defaultScore(className: string): number {
  return CLASS_SCORE[className] ?? 10;
}

function hashString(text: string): number {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function unit(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function offsetMeters(lat: number, lon: number, east: number, north: number): { lat: number; lon: number } {
  return {
    lat: lat + north / 111320,
    lon: lon + east / (111320 * Math.cos((lat * Math.PI) / 180)),
  };
}

function demoObjects(camera: Camera): TwinObject[] {
  if (camera.lat == null || camera.lon == null) return [];
  const random = unit(hashString(camera.camera_id));
  const count = 6 + Math.floor(random() * 7);
  const objects: TwinObject[] = [];
  for (let index = 0; index < count; index += 1) {
    const angle = random() * Math.PI * 2;
    const radius = 8 + random() * 32;
    const point = offsetMeters(camera.lat, camera.lon, Math.cos(angle) * radius, Math.sin(angle) * radius);
    const className = DEMO_CLASSES[index % DEMO_CLASSES.length];
    const riskScore = Math.round(15 + random() * 75);
    objects.push({
      trackId: 100 + index,
      className,
      lat: point.lat,
      lon: point.lon,
      riskScore,
      note: DEMO_NOTES[index % DEMO_NOTES.length],
      isDemo: true,
    });
  }
  return objects;
}

function placedDetection(cameraId: string, detection: Detection, reference?: CameraCalibration | null): TwinObject | null {
  const calibration = reference === undefined ? CALIBRATION[cameraId] : reference;
  // mapped_xz는 백엔드가 mapped_xz_corrected를 우선해 저장한 값이다.
  const mapped = detection.mapped_xz;
  if (!calibration || !mapped || mapped.length < 2) return null;
  const point = xzToLatLon(calibration.originLat, calibration.originLon, mapped[0], mapped[1]);
  const raw = detection.risk_score;
  return {
    trackId: detection.track_id,
    className: detection.class_name,
    lat: point.lat,
    lon: point.lon,
    riskScore: raw == null ? defaultScore(detection.class_name) : raw,
    isDemo: false,
  };
}

/** TODO: 캘리브레이션과 risk_score가 오면 예시 분기를 지우면 된다. */
export function objectsForCamera(camera: Camera, frame: OverlayState | LatestFrame | null, reference?: CameraCalibration | null): TwinObject[] {
  const detections = frame == null ? [] : "boxes" in frame ? frame.boxes : frame.detections;
  const placed = detections
    .map((detection) => placedDetection(camera.camera_id, detection, reference))
    .filter((item): item is TwinObject => item !== null);
  if (placed.length) return placed;
  if (!demoTwinEnabled()) return [];
  return demoObjects(camera);
}

// 임시값. 경고 레코드에 risk_score가 생기면 그 값을 쓰고 이 표는 버린다.
const SEVERITY_SCORE: Record<string, number> = {
  high: 80,
  medium: 55,
  low: 30,
  warning: 55,
};

function alertTimeMs(alert: AlertItem): number {
  const created = new Date(alert.created_at).getTime();
  if (!Number.isNaN(created)) return created;
  return alert.timestamp > 1e12 ? alert.timestamp : alert.timestamp * 1000;
}

export function riskEvents(alerts: AlertItem[]): RiskEvent[] {
  return alerts.map((alert) => {
    const given = alert.risk_score;
    const score = given == null ? (SEVERITY_SCORE[alert.severity] ?? 55) : given;
    return {
      id: alert.id,
      cameraId: alert.camera_id,
      type: alert.type,
      message: alert.message,
      timeMs: alertTimeMs(alert),
      riskScore: score,
      status: alert.status,
      isDemo: given == null,
    };
  });
}

const SEGMENT_TEMPLATES = [
  { detail: "도로 파손 9 · 낙하물 3", count: 12 },
  { detail: "차량 추돌 의심 6 · 방호벽 충돌 의심 4", count: 10 },
  { detail: "도로 파손 7 · 낙하물 2", count: 9 },
  { detail: "차량 추돌 의심 5 · 낙하물 2", count: 7 },
  { detail: "도로 파손 4 · 방호벽 충돌 의심 1", count: 5 },
];

export function repeatedSegments(cameras: Camera[]): RepeatedSegment[] {
  if (!demoTwinEnabled()) return [];
  const located = cameras.filter((camera) => camera.lat != null && camera.lon != null);
  return located.slice(0, SEGMENT_TEMPLATES.length).map((camera, index) => {
    const item = SEGMENT_TEMPLATES[index];
    const place = splitPlace(camera.name, camera.camera_id);
    return {
      rank: index + 1,
      name: `${place.title} 부근`,
      detail: item.detail,
      count: item.count,
      lat: camera.lat as number,
      lon: camera.lon as number,
      isDemo: true,
    };
  });
}

export function heatPoints(cameras: Camera[], segments: RepeatedSegment[]): HeatPoint[] {
  if (!demoTwinEnabled()) return [];
  const points: HeatPoint[] = [];
  const located = cameras.filter((camera) => camera.lat != null && camera.lon != null);
  for (const camera of located) {
    const weight = 0.25 + (hashString(camera.camera_id) % 75) / 100;
    points.push({ lat: camera.lat as number, lon: camera.lon as number, weight, isDemo: true });
  }
  for (const segment of segments) {
    points.push({ lat: segment.lat, lon: segment.lon, weight: segment.count / 12, isDemo: true });
  }
  return points;
}

function hourOf(iso: string): number | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  const hour = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    hourCycle: "h23",
  }).format(date);
  const value = Number(hour === "24" ? "0" : hour);
  return Number.isFinite(value) ? value : null;
}

const DEMO_HOURS = [1, 1, 0, 0, 1, 3, 6, 11, 14, 9, 7, 6, 8, 9, 8, 10, 13, 16, 12, 8, 5, 3, 2, 1];

function emptyHours(): HourBucket[] {
  return Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
}

/** 전체 클래스 검출 수. 위험 이벤트가 아니다. */
export function hourlyDetections(byHour: { hour: string; count: number }[] | null): HourBucket[] {
  const rows = emptyHours();
  for (const item of byHour ?? []) {
    const hour = hourOf(item.hour);
    if (hour == null) continue;
    rows[hour].count += item.count;
  }
  return rows;
}

/** 위험 이벤트 시간대 집계 API는 아직 없다. 데모일 때만 예시 값을 쓴다. */
export function hourlyRisk(): { rows: HourBucket[]; isDemo: boolean } {
  if (!demoTwinEnabled()) return { rows: emptyHours(), isDemo: false };
  return { rows: DEMO_HOURS.map((count, hour) => ({ hour, count })), isDemo: true };
}

const DEMO_TYPES: TypeCount[] = [
  { type: "road_damage", count: 18 },
  { type: "road_debris", count: 11 },
  { type: "suspected_vehicle_collision", count: 8 },
  { type: "suspected_vehicle_structure_collision", count: 3 },
];

export function riskByType(): { rows: TypeCount[]; isDemo: boolean } {
  if (!demoTwinEnabled()) return { rows: [], isDemo: false };
  return { rows: DEMO_TYPES, isDemo: true };
}

export function passesRisk(score: number, levels: { high: boolean; mid: boolean; low: boolean }): boolean {
  const level = riskLevel(score);
  return levels[level];
}
