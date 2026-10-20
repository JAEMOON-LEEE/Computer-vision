import type { Camera, DetectionStats } from "./types";

export type Period = "live" | "1h" | "today" | "7d";
export type CameraStatusFilter = "all" | "online" | "alert";

/** 0은 미확인 경고가 없는 카메라, 1·3은 그 건수 이상. null이면 건수로 거르지 않는다. */
export type AlertCountFilter = 0 | 1 | 3 | null;

export type Filters = {
  classes: string[];
  alertCount: AlertCountFilter;
  period: Period;
  cameraStatus: CameraStatusFilter;
};

export const DEFAULT_FILTERS: Filters = {
  classes: [],
  alertCount: null,
  period: "1h",
  cameraStatus: "all",
};

const VEHICLES = new Set(["car", "truck", "bus", "motorcycle", "bicycle"]);
const PEOPLE = new Set(["person"]);
const DEFECTS = new Set(["pothole", "crack", "debris"]);

export type ClassTotals = {
  total: number;
  vehicle: number;
  person: number;
  defect: number;
  latestHour: string;
};

export function splitPlace(name: string | null, cameraId: string): { title: string; road: string } {
  const text = (name || cameraId).trim();
  const match = text.match(/^\[(.+?)\]\s*(.*)$/);
  if (!match) return { title: text, road: "도로명 없음" };
  return { title: match[2] || text, road: match[1] };
}

// TODO: 백엔드 응답에 risk_score가 생기면 미확인 경고 수 대신 그 필드로 위험도를 거른다.

export function matchesAlertCount(count: number, filter: AlertCountFilter): boolean {
  if (filter === null) return true;
  if (filter === 0) return count === 0;
  return count >= filter;
}

export function isOffline(camera: Camera): boolean {
  return camera.status.toLowerCase() === "offline";
}

export function periodLabel(period: Period): string {
  if (period === "live") return "최근 10분";
  if (period === "today") return "오늘";
  if (period === "7d") return "최근 7일";
  return "최근 1시간";
}

function kstStamp(date: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "00";
  const hour = pick("hour") === "24" ? "00" : pick("hour");
  return `${pick("year")}-${pick("month")}-${pick("day")}T${hour}:${pick("minute")}:${pick("second")}+09:00`;
}

export function periodRange(period: Period, now = new Date()): { from: string; to: string } {
  const to = kstStamp(now);
  if (period === "live") return { from: kstStamp(new Date(now.getTime() - 10 * 60 * 1000)), to };
  if (period === "1h") return { from: kstStamp(new Date(now.getTime() - 60 * 60 * 1000)), to };
  if (period === "7d") return { from: kstStamp(new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)), to };
  return { from: `${kstStamp(now).slice(0, 10)}T00:00:00+09:00`, to };
}

export function summarize(stats: DetectionStats | undefined, classes: string[]): ClassTotals {
  const allowed = classes.length ? new Set(classes) : null;
  const totals: ClassTotals = { total: 0, vehicle: 0, person: 0, defect: 0, latestHour: "" };
  for (const row of stats?.by_class ?? []) {
    if (allowed && !allowed.has(row.class_name)) continue;
    totals.total += row.count;
    if (VEHICLES.has(row.class_name)) totals.vehicle += row.count;
    if (PEOPLE.has(row.class_name)) totals.person += row.count;
    if (DEFECTS.has(row.class_name)) totals.defect += row.count;
  }
  const hours = [...(stats?.by_hour ?? [])].sort((a, b) => (a.hour < b.hour ? 1 : -1));
  totals.latestHour = hours.find((row) => row.count > 0)?.hour ?? "";
  return totals;
}
