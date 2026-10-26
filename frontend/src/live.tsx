import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { getAlerts, getCameras, getUnconfirmedAlerts, patchAlert, wsUrl } from "./api";
import type { AlertItem, Camera, FrameRecord, LatencySample, OverlayState } from "./types";
import { DEFAULT_CAMERA } from "./types";

type LiveValue = {
  cameras: Camera[];
  camerasError: string;
  alerts: AlertItem[];
  unconfirmedAlerts: AlertItem[];
  alertError: string;
  selectedId: string;
  wsStatus: string;
  overlayRef: MutableRefObject<OverlayState>;
  latencyRef: MutableRefObject<LatencySample[]>;
  latencyTick: number;
  selectCamera: (cameraId: string) => void;
  confirmAlert: (id: number) => Promise<void>;
  dismissAlert: (id: number) => Promise<void>;
  applyFrame: (frame: FrameRecord, measure: boolean) => void;
  noteLatency: () => void;
  clearLatency: () => void;
};

const LiveContext = createContext<LiveValue | null>(null);

function emptyOverlay(cameraId: string): OverlayState {
  return {
    cameraId,
    width: 1280,
    height: 720,
    boxes: [],
    updatedAt: 0,
    timestamp: 0,
    timestampKind: "",
    frame: -1,
    pendingMeasure: false,
  };
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [unconfirmedAlerts, setUnconfirmedAlerts] = useState<AlertItem[]>([]);
  const [alertError, setAlertError] = useState("");
  const [camerasError, setCamerasError] = useState("");
  const [selectedId, setSelectedId] = useState(DEFAULT_CAMERA);
  const [wsStatus, setWsStatus] = useState("연결 중");
  const [latencyTick, setLatencyTick] = useState(0);
  const overlayRef = useRef<OverlayState>(emptyOverlay(DEFAULT_CAMERA));
  const latencyRef = useRef<LatencySample[]>([]);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;

  const bumpLatency = useCallback(() => {
    setLatencyTick((value) => value + 1);
  }, []);

  const applyFrame = useCallback((frame: FrameRecord, measure: boolean) => {
    if (frame.camera_id !== selectedRef.current) return;
    overlayRef.current = {
      cameraId: frame.camera_id,
      runId: frame.run_id,
      width: frame.width || overlayRef.current.width,
      height: frame.height || overlayRef.current.height,
      boxes: frame.detections ?? [],
      updatedAt: Date.now(),
      timestamp: frame.timestamp,
      timestampKind: frame.timestamp_kind,
      frame: frame.frame,
      pendingMeasure: measure && (frame.detections?.length ?? 0) > 0,
    };
  }, []);

  const selectCamera = useCallback((cameraId: string) => {
    selectedRef.current = cameraId;
    overlayRef.current = emptyOverlay(cameraId);
    setSelectedId(cameraId);
  }, []);

  const replaceAlert = useCallback((alert: AlertItem) => {
    if (alert.camera_id !== selectedRef.current) return;
    setAlerts((current) => {
      const index = current.findIndex((item) => item.id === alert.id);
      const next = index >= 0 ? current.map((item, i) => (i === index ? alert : item)) : [alert, ...current];
      return next.sort((a, b) => b.timestamp - a.timestamp || b.id - a.id);
    });
  }, []);

  const applyUnconfirmed = useCallback((alert: AlertItem) => {
    setUnconfirmedAlerts((current) => {
      const without = current.filter((item) => item.id !== alert.id);
      if (alert.status !== "unconfirmed") return without;
      return [alert, ...without].sort((a, b) => b.timestamp - a.timestamp || b.id - a.id);
    });
  }, []);

  const confirmAlert = useCallback(
    async (id: number) => {
      setAlertError("");
      try {
        const updated = await patchAlert(id, "confirmed");
        replaceAlert(updated);
        applyUnconfirmed(updated);
      } catch (error) {
        setAlertError(error instanceof Error ? error.message : "경고 상태 변경 실패");
      }
    },
    [replaceAlert, applyUnconfirmed],
  );

  const dismissAlert = useCallback(
    async (id: number) => {
      setAlertError("");
      try {
        const updated = await patchAlert(id, "dismissed");
        replaceAlert(updated);
        applyUnconfirmed(updated);
      } catch (error) {
        setAlertError(error instanceof Error ? error.message : "경고 상태 변경 실패");
      }
    },
    [replaceAlert, applyUnconfirmed],
  );

  const clearLatency = useCallback(() => {
    latencyRef.current = [];
    bumpLatency();
  }, [bumpLatency]);

  useEffect(() => {
    let stopped = false;
    const load = () => { getCameras()
      .then((rows) => {
        if (!stopped) {
          setCameras(rows);
          setCamerasError("");
        }
      })
      .catch((error: unknown) => {
        if (!stopped) setCamerasError(error instanceof Error ? error.message : "카메라 목록 실패");
      });
    };
    load();
    window.addEventListener("twinsight-data-updated", load);
    return () => {
      window.removeEventListener("twinsight-data-updated", load);
      stopped = true;
    };
  }, []);

  // 전체 미확인 경고. 실시간 이벤트 사이에 빠진 건 60초마다 다시 맞춘다.
  useEffect(() => {
    let stopped = false;
    const load = () => {
      getUnconfirmedAlerts()
        .then((rows) => {
          if (!stopped) setUnconfirmedAlerts(rows);
        })
        .catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    getAlerts(selectedId)
      .then((rows) => {
        if (!stopped) {
          setAlerts(rows);
          setAlertError("");
        }
      })
      .catch((error: unknown) => {
        if (!stopped) setAlertError(error instanceof Error ? error.message : "경고 조회 실패");
      });
    return () => {
      stopped = true;
    };
  }, [selectedId]);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let timer = 0;
    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(wsUrl());
      socket = ws;
      ws.onopen = () => setWsStatus("실시간 연결됨");
      ws.onerror = () => setWsStatus("연결 실패");
      ws.onclose = () => {
        if (stopped) return;
        setWsStatus("연결 끊김, 3초 후 재접속");
        timer = window.setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        let message: {
          type?: string;
          run_id?: string;
          camera_id?: string;
          frame?: FrameRecord;
          alert?: AlertItem;
        };
        try {
          message = JSON.parse(String(event.data)) as typeof message;
        } catch {
          return;
        }
        if (message.type === "detections" && message.frame && message.camera_id) {
          applyFrame({ ...message.frame, run_id: message.run_id || message.frame.run_id, camera_id: message.frame.camera_id || message.camera_id }, true);
        } else if (message.type === "alert" && message.alert) {
          replaceAlert(message.alert);
          if (message.alert.status === "unconfirmed") applyUnconfirmed(message.alert);
        } else if (message.type === "alert_updated" && message.alert) {
          replaceAlert(message.alert);
          applyUnconfirmed(message.alert);
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [applyFrame, replaceAlert, applyUnconfirmed]);

  const value = useMemo<LiveValue>(
    () => ({
      cameras,
      camerasError,
      alerts,
      unconfirmedAlerts,
      alertError,
      selectedId,
      wsStatus,
      overlayRef,
      latencyRef,
      latencyTick,
      selectCamera,
      confirmAlert,
      dismissAlert,
      noteLatency: bumpLatency,
      applyFrame,
      clearLatency,
    }),
    [
      cameras,
      camerasError,
      alerts,
      unconfirmedAlerts,
      alertError,
      selectedId,
      wsStatus,
      latencyTick,
      selectCamera,
      confirmAlert,
      dismissAlert,
      bumpLatency,
      applyFrame,
      clearLatency,
    ],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveValue {
  const value = useContext(LiveContext);
  if (!value) throw new Error("LiveProvider 밖에서 useLive를 호출했습니다");
  return value;
}

export function recordLatency(sample: LatencySample, samples: LatencySample[], bump: () => void) {
  samples.push(sample);
  if (samples.length > 2000) samples.splice(0, samples.length - 2000);
  if (samples.length === 1 || samples.length % 10 === 0) bump();
}

export function latencyStats(samples: LatencySample[]) {
  if (!samples.length) return { avg: null as number | null, p95: null as number | null, max: null as number | null, n: 0 };
  const values = samples.map((sample) => sample.latencyMs).sort((a, b) => a - b);
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length;
  const index = Math.min(values.length - 1, Math.ceil(0.95 * values.length) - 1);
  return { avg, p95: values[index], max: values[values.length - 1], n: values.length };
}
