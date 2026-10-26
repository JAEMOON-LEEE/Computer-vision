import type { AlertItem, Camera, DetectionList, DetectionStats, LatestFrame, StreamInfo } from "./types";

export const API_BASE = new URL(import.meta.env.VITE_API_BASE || "/api", window.location.origin).toString().replace(/\/$/, "");

export function wsUrl(): string {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = url.pathname.replace(/\/$/, "") + "/ws";
  url.search = "";
  url.hash = "";
  return url.toString();
}

async function readError(response: Response): Promise<string> {
  if (response.status === 401) {
    window.location.assign("/login");
    return "다시 로그인하세요";
  }
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item: { loc?: string[]; msg?: string }) =>
      `${item.loc?.slice(1).join(".") || "입력"}: ${item.msg || "값을 확인하세요"}`).join(" / ");
  } catch {
    /* 본문이 JSON이 아니면 상태 코드만 쓴다. */
  }
  return String(response.status);
}

export async function getCameras(): Promise<Camera[]> {
  const response = await fetch(`${API_BASE}/cameras`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<Camera[]>;
}

export async function getStream(cameraId: string): Promise<StreamInfo> {
  const response = await fetch(`${API_BASE}/cameras/${encodeURIComponent(cameraId)}/stream`);
  const body = (await response.json()) as StreamInfo & { detail?: string };
  if (!response.ok) throw new Error(body.detail || String(response.status));
  return body;
}

export async function getLatest(cameraId: string): Promise<LatestFrame | null> {
  const response = await fetch(`${API_BASE}/cameras/${encodeURIComponent(cameraId)}/detections/latest`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<LatestFrame>;
}

export async function getDetections(params: URLSearchParams): Promise<DetectionList> {
  const response = await fetch(`${API_BASE}/detections?${params.toString()}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<DetectionList>;
}

export async function getDetectionStats(params: URLSearchParams): Promise<DetectionStats> {
  const response = await fetch(`${API_BASE}/detections/stats?${params.toString()}`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<DetectionStats>;
}

export async function getUnconfirmedAlerts(): Promise<AlertItem[]> {
  const response = await fetch(`${API_BASE}/alerts?status=unconfirmed&limit=1000`);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AlertItem[]>;
}

export async function getAlerts(cameraId: string): Promise<AlertItem[]> {
  const response = await fetch(
    `${API_BASE}/alerts?camera_id=${encodeURIComponent(cameraId)}&limit=50`,
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AlertItem[]>;
}

export async function patchAlert(id: number, status: "confirmed" | "dismissed"): Promise<AlertItem> {
  const response = await fetch(`${API_BASE}/alerts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, handled_by: "dashboard" }),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<AlertItem>;
}


export async function databaseRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/database${path}`, init);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}
