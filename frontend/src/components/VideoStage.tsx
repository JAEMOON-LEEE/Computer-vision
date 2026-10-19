import Hls from "hls.js";
import { memo, useEffect, useRef, useState, type MutableRefObject } from "react";
import { getStream } from "../api";
import { classColor } from "../colors";
import { recordLatency } from "../live";
import type { LatencySample, OverlayState } from "../types";

const HOLD_MS = 500;

type Props = {
  cameraId: string;
  overlayRef: MutableRefObject<OverlayState>;
  latencyRef: MutableRefObject<LatencySample[]>;
  onSample: () => void;
};

function contentRect(width: number, height: number, sourceWidth: number, sourceHeight: number) {
  const sourceRatio = sourceWidth / sourceHeight;
  const elementRatio = width / Math.max(height, 1);
  if (elementRatio > sourceRatio) {
    const drawHeight = height;
    const drawWidth = height * sourceRatio;
    return { x: (width - drawWidth) / 2, y: 0, width: drawWidth, height: drawHeight };
  }
  const drawWidth = width;
  const drawHeight = width / sourceRatio;
  return { x: 0, y: (height - drawHeight) / 2, width: drawWidth, height: drawHeight };
}

function draw(
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement | null,
  overlay: OverlayState,
  cameraId: string,
) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const pixelWidth = Math.max(1, Math.round(rect.width * ratio));
  const pixelHeight = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  if (overlay.cameraId !== cameraId || !overlay.boxes.length || rect.width < 2) return;
  const sourceWidth = video?.videoWidth || overlay.width || 16;
  const sourceHeight = video?.videoHeight || overlay.height || 9;
  const area = contentRect(rect.width, rect.height, sourceWidth, sourceHeight);
  const scaleX = area.width / (overlay.width || sourceWidth);
  const scaleY = area.height / (overlay.height || sourceHeight);
  context.lineWidth = 2;
  context.font = "13px Segoe UI, sans-serif";
  for (const detection of overlay.boxes) {
    const box = detection.bbox_xyxy;
    if (!box || box.length !== 4) continue;
    const x = area.x + box[0] * scaleX;
    const y = area.y + box[1] * scaleY;
    const w = (box[2] - box[0]) * scaleX;
    const h = (box[3] - box[1]) * scaleY;
    const color = classColor(detection.class_name);
    context.strokeStyle = color;
    context.strokeRect(x, y, w, h);
    const label = `${detection.class_name} #${detection.track_id ?? "-"} ${Number(detection.confidence).toFixed(2)}`;
    const textWidth = context.measureText(label).width;
    context.fillStyle = "rgba(0,0,0,0.65)";
    context.fillRect(x, Math.max(0, y - 18), textWidth + 8, 18);
    context.fillStyle = color;
    context.fillText(label, x + 4, Math.max(12, y - 5));
  }
}

export const VideoStage = memo(function VideoStage({ cameraId, overlayRef, latencyRef, onSample }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [note, setNote] = useState("스트림을 기다리는 중");

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let hls: Hls | null = null;
    let cancelled = false;
    setNote("스트림 주소를 요청하는 중");
    getStream(cameraId)
      .then((data) => {
        if (cancelled) return;
        if (data.warning) setNote(data.warning);
        else setNote(data.refreshed ? "스트림 주소를 갱신했습니다" : "저장된 스트림을 재생합니다");
        if (Hls.isSupported()) {
          hls = new Hls();
          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            video.play().catch(() => undefined);
          });
          hls.on(Hls.Events.ERROR, (_event, detail) => {
            if (detail.fatal) setNote(`재생 오류: ${detail.details}`);
          });
          hls.loadSource(data.stream_url);
          hls.attachMedia(video);
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.src = data.stream_url;
          setNote("브라우저 기본 HLS로 재생합니다");
        } else {
          setNote("이 브라우저는 HLS를 재생하지 못합니다.");
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setNote(error instanceof Error ? error.message : "스트림 요청 실패");
      });
    return () => {
      cancelled = true;
      hls?.destroy();
      video.removeAttribute("src");
      video.load();
    };
  }, [cameraId]);

  useEffect(() => {
    let frameId = 0;
    const loop = () => {
      const canvas = canvasRef.current;
      const overlay = overlayRef.current;
      const now = Date.now();
      if (
        overlay.cameraId === cameraId &&
        overlay.boxes.length > 0 &&
        overlay.updatedAt > 0 &&
        now - overlay.updatedAt > HOLD_MS
      ) {
        overlay.boxes = [];
        overlay.pendingMeasure = false;
      }
      if (canvas) draw(canvas, videoRef.current, overlay, cameraId);
      if (overlay.cameraId === cameraId && overlay.pendingMeasure && overlay.boxes.length > 0) {
        const useTimestamp = overlay.timestampKind === "unix_seconds";
        recordLatency(
          {
            cameraId,
            frame: overlay.frame,
            timestamp: overlay.timestamp,
            timestampKind: overlay.timestampKind,
            latencyMs: useTimestamp ? now - overlay.timestamp * 1000 : now - overlay.updatedAt,
            basis: useTimestamp ? "timestamp" : "received",
          },
          latencyRef.current,
          onSample,
        );
        overlay.pendingMeasure = false;
      }
      frameId = requestAnimationFrame(loop);
    };
    frameId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frameId);
  }, [cameraId, latencyRef, onSample, overlayRef]);

  return (
    <div className="stage-wrap">
      <div className="stage">
        <video ref={videoRef} muted autoPlay playsInline controls />
        <canvas ref={canvasRef} />
      </div>
      <p className="note">목업 박스는 실제 영상 속 물체와 위치가 맞지 않습니다. 오버레이 동작 확인용입니다.</p>
      <p className="stream-note">{note}</p>
    </div>
  );
});
