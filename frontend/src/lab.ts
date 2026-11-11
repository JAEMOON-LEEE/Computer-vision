import { API_BASE } from "./api";

export type SourceKind = "image" | "video" | "screen";
export type LabDetection = { class_name: string; confidence: number; bbox_xyxy: number[]; track_id: number | null };
export type LabAlert = { type: string; timestamp: number; message: string };
export type LabFrame = { timestamp: number; width: number; height: number; frame: number; inference_ms: number;
  detections: LabDetection[]; alerts: LabAlert[]; history_reset: string | null; request_id: string };
export type LabSession = { session_id: string; enabled: boolean; output_directory: string };

export async function labRequest<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}/lab/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `분석 서버 요청 실패 (${response.status})`);
  return data as T;
}

export function youtubeReference(raw: string): { id: string; start: number; url: string } | null {
  try {
    const url = new URL(raw);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    const host = url.hostname.toLowerCase().replace(/^www\./, "");
    let id: string | null = null;
    if (host === "youtu.be") id = url.pathname.split("/")[1];
    if (["youtube.com", "m.youtube.com", "youtube-nocookie.com"].includes(host)) {
      id = url.searchParams.get("v");
      if (!id && /\/(embed|shorts|live)\//.test(url.pathname)) id = url.pathname.split("/")[2];
    }
    if (!id || !/^[\w-]{11}$/.test(id)) return null;
    const time = url.searchParams.get("t") || url.searchParams.get("start") || "0";
    const match = time.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$/);
    const start = match ? Math.min(86400, Number(match[1] || 0)*3600 + Number(match[2] || 0)*60 + Number(match[3] || 0)) : 0;
    return { id, start, url: `https://www.youtube.com/watch?v=${id}&t=${start}s` };
  } catch { return null; }
}

export function validCrop(crop: number[]) {
  const [x, y, w, h] = crop;
  return crop.every(Number.isFinite) && x >= 0 && y >= 0 && w > 0 && h > 0 && x+w <= 100 && y+h <= 100;
}

export function clock(seconds: number) {
  return `${Math.floor(seconds/60).toString().padStart(2, "0")}:${(seconds%60).toFixed(2).padStart(5, "0")}`;
}

export const classLabels: Record<string, string> = { person: "보행자", car: "승용차", truck: "트럭", bus: "버스", motorcycle: "오토바이", bicycle: "자전거", pothole: "포트홀", debris: "낙하물", barrier: "구조물" };
export const alertLabels: Record<string, string> = { road_damage: "도로 파임 의심", road_debris: "도로 낙하물 의심", suspected_vehicle_collision: "차량 추돌 의심", suspected_vehicle_structure_collision: "구조물 충돌 의심", suspected_traffic_incident_scene:"실제 사고 장면 의심 · 구간 검토" };
