// 시연 화면의 실시간 검출: 브라우저 안 Unity 화면을 잘라 백엔드(/demo/detect)로 보내고 박스·경고를 받는다.
// 백엔드는 팀 검출 모델(주야간 + 시설물 실험 모델)만 쓰며 Unity의 시나리오 정답은 보내지 않는다.
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";
import { send, unityCanvas } from "./unity";

export const FRAME_W = 768; // 학습 화면(1440×960)과 같은 3:2
export const FRAME_H = 512;
const INTERVAL_MS = 250;

export type DemoDetection = { class_name: string; confidence: number; bbox_xyxy: number[] };
export type DemoAlert = {
  alert_id: string;
  type: string;
  message: string;
  timestamp: number;
  status: string;
  evidence: { class_name: string; confidence: number; bbox_xyxy: number[] }[];
};
type DetectResponse = {
  frame: number;
  width: number;
  height: number;
  inference_ms: number;
  detections: DemoDetection[];
  alerts: DemoAlert[];
};

export const CLASS_KO: Record<string, string> = {
  pothole: "포트홀",
  crack: "균열",
  debris: "낙하물",
  delineator_normal: "유도봉 정상",
  delineator_broken: "유도봉 부러짐",
  delineator_fallen: "유도봉 쓰러짐",
  manhole_normal: "맨홀 정상",
  manhole_abnormal: "맨홀 이상",
  guardrail_normal: "가드레일 정상",
  guardrail_abnormal: "가드레일 이상",
};

export const ALERT_KO: Record<string, string> = {
  road_damage: "노면 손상",
  road_debris: "낙하물",
  facility_damage: "시설물 파손",
  manhole_abnormal: "맨홀 이상",
};

export function isAbnormal(name: string) {
  return !name.endsWith("_normal");
}

// Unity가 가상 CCTV를 960×640으로 따로 렌더링해 돌려준다(창 크기와 무관, 학습 화면과 같은 3:2).
// 응답이 없으면(예전 빌드) 화면 캔버스를 잘라 쓴다.
function captureFromUnity(timeoutMs = 1500): Promise<string> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      window.removeEventListener("twinsight-frame", onFrame);
      reject(new Error("timeout"));
    }, timeoutMs);
    function onFrame(e: Event) {
      window.clearTimeout(timer);
      window.removeEventListener("twinsight-frame", onFrame);
      resolve((e as CustomEvent<string>).detail);
    }
    window.addEventListener("twinsight-frame", onFrame);
    send("CaptureFrame");
  });
}

let unityCaptureWorks = true;

async function capture(): Promise<string> {
  if (unityCaptureWorks) {
    try {
      return await captureFromUnity();
    } catch {
      unityCaptureWorks = false;
    }
  }
  return captureCanvas();
}

function captureCanvas(): Promise<string> {
  const source = unityCanvas();
  const frame = document.createElement("canvas");
  frame.width = FRAME_W;
  frame.height = FRAME_H;
  const ctx = frame.getContext("2d");
  if (!ctx || source.width === 0) return Promise.reject(new Error("Unity 화면이 아직 없습니다"));
  ctx.drawImage(source, 0, 0, FRAME_W, FRAME_H);
  return new Promise((resolve, reject) =>
    frame.toBlob(
      (blob) => {
        if (!blob) return reject(new Error("화면을 저장하지 못했습니다"));
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(new Error("화면을 읽지 못했습니다"));
        reader.readAsDataURL(blob);
      },
      "image/jpeg",
      0.88,
    ),
  );
}

// 실제 CCTV 영상(<video>)의 현재 프레임을 원본 해상도로 JPEG로 만든다
function captureVideo(video: HTMLVideoElement): Promise<{ image: string; t: number }> {
  const w = video.videoWidth, h = video.videoHeight;
  if (!w || !h) return Promise.reject(new Error("영상이 아직 준비되지 않았습니다"));
  const frame = document.createElement("canvas");
  frame.width = w;
  frame.height = h;
  frame.getContext("2d")!.drawImage(video, 0, 0, w, h);
  const t = video.currentTime;
  return new Promise((resolve, reject) =>
    frame.toBlob(
      (blob) => {
        if (!blob) return reject(new Error("영상 프레임을 저장하지 못했습니다"));
        const reader = new FileReader();
        reader.onload = () => resolve({ image: reader.result as string, t });
        reader.readAsDataURL(blob);
      },
      "image/jpeg",
      0.9,
    ),
  );
}

export function useLiveDetection(enabled: boolean, video?: React.RefObject<HTMLVideoElement | null>, unitySource: "sim" | "twin" = "sim") {
  const source = video ? "real" : unitySource;
  const [result, setResult] = useState<DetectResponse | null>(null);
  const [alerts, setAlerts] = useState<(DemoAlert & { at: number })[]>([]);
  const [error, setError] = useState("");
  const [fps, setFps] = useState(0);
  const stamps = useRef<number[]>([]);

  useEffect(() => {
    if (!enabled) {
      setResult(null);
      return;
    }
    let alive = true;
    setError("");
    fetch(`${API_BASE}/demo/reset?source=${source}`, { method: "POST" }).catch(() => undefined);
    let lastVideoTime = -1;
    (async () => {
      while (alive) {
        const started = performance.now();
        try {
          let image_b64: string, timestamp: number;
          if (video) {
            const v = video.current;
            if (!v || v.paused || v.currentTime === lastVideoTime) {
              await new Promise((r) => setTimeout(r, 120));   // 멈춘 영상은 같은 프레임을 다시 보내지 않는다
              continue;
            }
            const shot = await captureVideo(v);
            image_b64 = shot.image;
            timestamp = shot.t;
            lastVideoTime = shot.t;
          } else {
            image_b64 = await capture();
            timestamp = started / 1000;
          }
          const res = await fetch(`${API_BASE}/demo/detect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ image_b64, timestamp, source }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(typeof body.detail === "string" ? body.detail : `검출 서버 오류 ${res.status}`);
          }
          const data: DetectResponse = await res.json();
          if (!alive) break;
          setResult(data);
          setError("");
          if (data.alerts.length)
            setAlerts((list) => [...data.alerts.map((a) => ({ ...a, at: Date.now() })), ...list].slice(0, 10));
          const now = performance.now();
          stamps.current = [...stamps.current.filter((t) => now - t < 3000), now];
          setFps(stamps.current.length / 3);
        } catch (e) {
          if (!alive) break;
          const message = e instanceof TypeError
            ? `검출 서버(${API_BASE})에 연결하지 못했습니다. 저장소 루트에서 백엔드를 실행하세요.`
            : (e as Error).message;
          setError(message);
          await new Promise((r) => setTimeout(r, 2000));
          continue;
        }
        const wait = INTERVAL_MS - (performance.now() - started);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      }
    })();
    return () => {
      alive = false;
    };
  }, [enabled, source]);

  return { result, alerts, error, fps, clearAlerts: () => setAlerts([]) };
}
