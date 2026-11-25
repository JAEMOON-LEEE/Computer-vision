// Unity WebGL 빌드(frontend/public/unity, simulation/.../WebDemoBuild.cs가 생성)와의 연결.
// 캔버스와 인스턴스는 페이지를 오가도 한 번만 만든다(React StrictMode의 이중 마운트에도 안전).

export const UNITY_BASE = "/unity/Build/unity";
const BRIDGE = "TwinSightBridge";

export type UnityStatus = {
  type: "status";
  mode: "sim" | "twin";
  camera: string;
  scenario: string;
  variant?: string;
  signal_phase?: string;
  vehicle_light?: string;
  pedestrian_light?: string;
  signal_remaining?: number;
  night: boolean;
  auto_episodes: boolean;
  episode: number;
  vehicles: number;
  twin_frame: number;
  twin_frames: number;
  twin_vehicles: number;
  speed: number;
  time: number;
};

export type UnityEvent = {
  type: "event";
  scenario: string;
  variant?: string;
  event_type: string;
  relative_speed?: number;
  impulse?: number;
  evidence: string;
  episode: number;
  time: number;
};

export type UnityMessage = UnityStatus | UnityEvent | { type: "ready"; mode: string };

type Instance = { SendMessage: (obj: string, method: string, value?: string) => void };
type CreateUnity = (
  canvas: HTMLCanvasElement,
  config: Record<string, unknown>,
  onProgress?: (p: number) => void,
) => Promise<Instance>;

let canvas: HTMLCanvasElement | null = null;
let starting: Promise<Instance> | null = null;
let instance: Instance | null = null;
const progressListeners = new Set<(p: number) => void>();

export function unityCanvas(): HTMLCanvasElement {
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "unity-canvas";
    canvas.tabIndex = -1;
    canvas.className = "unity-canvas";
  }
  return canvas;
}

export async function buildExists(): Promise<boolean> {
  try {
    const res = await fetch(`${UNITY_BASE}.loader.js`, { method: "HEAD" });
    const type = res.headers.get("content-type") || "";
    return res.ok && !type.includes("text/html");
  } catch {
    return false;
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-unity-loader]`);
    if (existing) return resolve();
    const script = document.createElement("script");
    script.src = src;
    script.dataset.unityLoader = "1";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Unity 로더를 불러오지 못했습니다"));
    document.body.appendChild(script);
  });
}

export function startUnity(onProgress: (p: number) => void): Promise<Instance> {
  progressListeners.add(onProgress);
  if (starting) return starting;
  starting = loadScript(`${UNITY_BASE}.loader.js`).then(() => {
    const create = (window as unknown as { createUnityInstance?: CreateUnity }).createUnityInstance;
    if (!create) throw new Error("createUnityInstance가 없습니다");
    return create(
      unityCanvas(),
      {
        dataUrl: `${UNITY_BASE}.data`,
        frameworkUrl: `${UNITY_BASE}.framework.js`,
        codeUrl: `${UNITY_BASE}.wasm`,
        streamingAssetsUrl: "/unity/StreamingAssets",
        companyName: "TwinSight",
        productName: "TwinSight City Lab",
        productVersion: "demo",
        devicePixelRatio: 1,
      },
      (p) => progressListeners.forEach((fn) => fn(p)),
    ).then((inst) => {
      instance = inst;
      return inst;
    });
  });
  starting.catch(() => {
    starting = null;
  });
  return starting;
}

export function offProgress(fn: (p: number) => void) {
  progressListeners.delete(fn);
}

export function send(method: string, value = "") {
  instance?.SendMessage(BRIDGE, method, value);
}

export function onUnityMessage(fn: (msg: UnityMessage) => void): () => void {
  const handler = (e: Event) => fn((e as CustomEvent<UnityMessage>).detail);
  window.addEventListener("twinsight-unity", handler);
  return () => window.removeEventListener("twinsight-unity", handler);
}
