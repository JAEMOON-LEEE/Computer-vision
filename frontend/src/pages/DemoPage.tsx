import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  buildExists,
  offProgress,
  onUnityMessage,
  send,
  startUnity,
  unityCanvas,
  type UnityEvent,
  type UnityStatus,
} from "../unity";
import { ALERT_KO, CLASS_KO, FRAME_W, isAbnormal, useLiveDetection, type DemoDetection } from "../demoDetection";
import { API_BASE } from "../api";
import "../demo.css";

type ScenarioKey = "Normal" | "Pothole" | "FallingDebris" | "RoadsideDamage" | "Manhole";
type Verdict = { label: string; text: string; ok: boolean };

// 검증 수치: 팀 보고(2026-11, 합성 영상)와 실제 CCTV 참고 영상 점검(2026-11-25, docs/validation/demo-real-cctv-check-20261125.json).
// Unity의 사고 장면은 시뮬레이션이다. "모델 경고"만 검출 모델이 낸 결과다.
const REAL_CHECK: Verdict = { label: "실제 CCTV 영상", text: "경고 0건", ok: false };
const SCENARIOS: {
  key: ScenarioKey;
  name: string;
  action: string;
  model: string;
  results: Verdict[];
  note: string;
  variants: { cmd: string; label: string }[];
}[] = [
  { key: "Pothole", name: "포트홀", action: "차로에 포트홀 만들기", model: "주야간 모델 · road_damage",
    results: [{ label: "주간 합성", text: "통과", ok: true }, { label: "야간 합성", text: "통과", ok: true }, REAL_CHECK],
    note: "합성 시나리오 경고는 통과했지만 실제 영상에서는 포트홀을 찾지 못했습니다.",
    variants: [
      { cmd: "Pothole:Small", label: "작은" }, { cmd: "Pothole:Wide", label: "넓은" },
      { cmd: "Pothole:Elongated", label: "길쭉한" }, { cmd: "Pothole:Cluster", label: "여러 개" },
    ] },
  { key: "FallingDebris", name: "낙하물", action: "콘크리트 낙하물 떨어뜨리기", model: "주야간 모델 · road_debris",
    results: [{ label: "주간 합성", text: "통과", ok: true }, { label: "야간 합성", text: "통과", ok: true }, REAL_CHECK],
    note: "실제 영상에서는 76프레임 중 11프레임만 낙하물로 보아 경고 조건(연속 검출)에 못 미쳤습니다.",
    variants: [
      { cmd: "Debris:SmallBlock", label: "작은 블록" }, { cmd: "Debris:LargeBlock", label: "큰 블록" },
      { cmd: "Debris:FlatSlab", label: "판재" }, { cmd: "Debris:MultipleBlocks", label: "여러 개" },
    ] },
  { key: "RoadsideDamage", name: "시설물 파손", action: "시선유도봉·가드레일 파손", model: "시설물 실험 모델(PR #4) · facility_damage",
    results: [{ label: "합성 AP50", text: "0.69~0.88", ok: true }, { label: "정상 가드레일 오경고", text: "39/100", ok: false }, REAL_CHECK],
    note: "AP50은 유도봉 파손 0.693·쓰러짐 0.777·가드레일 0.880(합성 시험). 오경고는 단일 프레임 기준이며 시연은 연속 검출로 거릅니다.",
    variants: [
      { cmd: "Facility:DelineatorFallen", label: "유도봉 쓰러짐" }, { cmd: "Facility:DelineatorBroken", label: "유도봉 부러짐" },
      { cmd: "Facility:GuardrailBent", label: "가드레일 휨" }, { cmd: "Facility:GuardrailBroken", label: "가드레일 끊어짐" },
      { cmd: "Facility:GuardrailDisplaced", label: "가드레일 밀림" },
      { cmd: "Facility:DelineatorNormal", label: "정상 유도봉" }, { cmd: "Facility:GuardrailNormal", label: "정상 가드레일" },
    ] },
  { key: "Manhole", name: "맨홀", action: "맨홀 뚜껑 이상", model: "시설물 실험 모델(PR #4) · manhole_abnormal",
    results: [{ label: "합성 AP50", text: "0.720", ok: true }, { label: "정상 맨홀 오경고", text: "19/80", ok: false }, REAL_CHECK],
    note: "오경고는 단일 프레임 기준이며 시연은 연속 검출로 거릅니다. 실제 영상(뉴스 화면)에서는 맨홀을 찾지 못했습니다.",
    variants: [
      { cmd: "Facility:ManholeOpen", label: "뚜껑 없음" }, { cmd: "Facility:ManholeDisplaced", label: "뚜껑 밀림" },
      { cmd: "Facility:ManholeDisplacedSmall", label: "조금 밀림" }, { cmd: "Facility:ManholeNormal", label: "정상 맨홀" },
    ] },
];

const EVENT_TEXT: Record<string, string> = {
  episode_started: "시나리오 시작",
  facility_setup: "시설물 장면 구성",
  pothole_created: "포트홀 생성",
  debris_dropped: "낙하물 떨어지기 시작",
  debris_landed: "낙하물이 노면에 닿음",
  collision_setup: "추돌 차량 출발",
  vehicle_collision: "차량끼리 접촉",
  structure_collision_setup: "충돌 차량이 방호벽으로 출발",
  vehicle_structure_collision: "차량이 방호벽에 접촉",
  varied_collision_setup: "충돌 차량 출발",
  stop_zone_case: "정지선 대기 장면 구성",
  stop_zone_rear_end_setup: "대기 차량 뒤로 추돌 차량 출발",
  stop_zone_structure_setup: "정지선 부근 방호벽으로 차량 출발",
  signal_violation_setup: "신호 위반 차량 출발",
  red_signal_crossing: "빨간불에 정지선 통과",
  delineator_knocked_down: "시선유도봉이 쓰러짐",
  guardrail_bent: "가드레일이 휨",
  guardrail_broken: "가드레일 조각이 차로로 떨어짐",
  manhole_cover_open: "맨홀 뚜껑이 열림",
  manhole_cover_raised: "맨홀 뚜껑이 들뜸",
  manhole_sunken: "맨홀 주변 노면이 내려앉음",
};

// 같은 종류의 실제 CCTV 영상(팀 공유 드라이브 "CCTV영상", frontend/public/demo-videos, Git 제외).
// Unity 장면과 나란히 보여 주는 참고 영상이며 검출 결과가 아니다.
const REAL_VIDEOS: Record<string, { src: string; label: string; source: string }> = {
  Pothole: { src: "/demo-videos/pothole.mp4", label: "포트홀", source: "도로 CCTV (융건릉입구)" },
  FallingDebris: { src: "/demo-videos/debris.mp4", label: "낙하물", source: "고속도로 CCTV (서해안선 서평택)" },
  Delineators: { src: "/demo-videos/delineator.mp4", label: "시선유도봉 손상", source: "도로 CCTV (학술림삼거리)" },
  Guardrail: { src: "/demo-videos/guardrail.mp4", label: "가드레일 손상", source: "도로 영상" },
  Manhole: { src: "/demo-videos/manhole.mp4", label: "맨홀 뚜껑 손상", source: "KBS 뉴스 영상" },
};

function realVideo(scenario?: string, variant?: string) {
  if (scenario === "RoadsideDamage") return !variant || variant.startsWith("Delineator") ? REAL_VIDEOS.Delineators : REAL_VIDEOS.Guardrail;
  return scenario ? REAL_VIDEOS[scenario] : undefined;
}

const DETECT_X = -3;

// 영상 재현 탭: 실제 CCTV 영상과 같은 구도의 Unity 재현(simulation/TwinSightSim/RealCctv/<폴더>)
const CASES: { key: string; label: string; video: string; replay: string; start?: number; end?: number; caption: string }[] = [
  { key: "pothole", label: "포트홀", video: "/demo-videos/pothole.mp4", replay: "RealCctv/yunggeon", caption: "융건릉입구 · 비 오는 날(물보라 지점 = 물 고인 포트홀 추정)" },
  { key: "debris", label: "낙하물", video: "/demo-videos/debris_youtube.mp4", replay: "RealCctv/seonpyeong", start: 0, end: 130, caption: "남해선 선평교 · 적재물 낙하(고속도로 CCTV, 유튜브 오토스)" },
  { key: "guardrail", label: "가드레일", video: "/demo-videos/guardrail.mp4", replay: "RealCctv/guardrail", caption: "고속도로 · 차량이 중앙 가드레일 충돌" },
  { key: "delineator", label: "시선유도봉", video: "/demo-videos/delineator.mp4", replay: "RealCctv/haksulrim", caption: "학술림삼거리 · 부러진 시선유도봉" },
  { key: "manhole", label: "맨홀", video: "/demo-videos/manhole.mp4", replay: "RealCctv/sanseong", caption: "대전 산성동 · KBS 뉴스 CCTV 화면" },
];

const CAMERAS = [
  { key: "incident", label: "사고 지점" },
  { key: "orbit", label: "회전" },
  { key: "cctv", label: "가상 CCTV" },
  { key: "overview", label: "전체" },
];

function SignIcon({ kind }: { kind: ScenarioKey }) {
  const glyph = {
    Normal: <path d="M32 22v20M24 34l8 8 8-8" />,
    Pothole: (
      <>
        <ellipse cx="32" cy="40" rx="12" ry="4.5" className="fill" />
        <path d="M20 40c2-6 6-8 12-8s10 2 12 8" />
      </>
    ),
    FallingDebris: (
      <>
        <rect x="27" y="22" width="9" height="7" className="fill" transform="rotate(-14 31 25)" />
        <rect x="22" y="36" width="8" height="6" className="fill" />
        <rect x="34" y="38" width="10" height="5" className="fill" />
      </>
    ),
    RoadsideDamage: (
      <>
        <path d="M18 44V30M26 44V30M17 33h10M17 38h10" />
        <rect x="35" y="27" width="4" height="17" rx="1.5" className="fill" />
        <rect x="41" y="38" width="4" height="13" rx="1.5" className="fill" transform="rotate(-62 43 44)" />
      </>
    ),
    Manhole: (
      <>
        <circle cx="32" cy="37" r="10" className="fill" />
        <path d="M26 33.5h12M25 37h14M26 40.5h12" className="grate" />
      </>
    ),
  }[kind];
  return (
    <svg viewBox="0 0 64 58" className="sign-icon" aria-hidden="true">
      <path d="M32 4 60 54H4Z" className="plate" />
      <g className="glyph">{glyph}</g>
    </svg>
  );
}

function DetectionOverlay({ detections, width, height }: { detections: DemoDetection[]; width: number; height: number }) {
  const k = width / FRAME_W; // 라벨 글자 크기를 프레임 크기와 상관없이 같게
  return (
    <svg className="detect-overlay" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      {detections.map((d, i) => {
        const [x1, y1, x2, y2] = d.bbox_xyxy;
        const bad = isAbnormal(d.class_name);
        const label = `${CLASS_KO[d.class_name] ?? d.class_name} ${d.confidence.toFixed(2)}`;
        return (
          <g key={i} className={bad ? "det bad" : "det ok"}>
            <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} />
            <rect className="tag" x={x1} y={Math.max(0, y1 - 17 * k)} width={(label.length * 7.2 + 8) * k} height={16 * k} />
            <text x={x1 + 4 * k} y={Math.max(12 * k, y1 - 5 * k)} fontSize={12 * k}>{label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function UnityStage({ twin, replay, aspect, inset, overlay }: { twin: boolean; replay?: boolean; aspect?: number; inset?: ReactNode; overlay?: ReactNode }) {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"checking" | "missing" | "loading" | "ready" | "error">("checking");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const onProgress = (p: number) => alive && setProgress(p);
    host.current?.appendChild(unityCanvas());
    buildExists().then((ok) => {
      if (!alive) return;
      if (!ok) return setState("missing");
      setState("loading");
      startUnity(onProgress)
        .then(() => alive && setState("ready"))
        .catch((e: Error) => {
          if (!alive) return;
          setError(e.message);
          setState("error");
        });
    });
    return () => {
      alive = false;
      offProgress(onProgress);
    };
  }, []);

  return (
    <div className={replay ? "stage replay" : twin ? "stage twin" : "stage"}>
      <div className="stage-canvas" style={aspect ? { aspectRatio: String(aspect) } : undefined}>
        <div ref={host} className="canvas-host" />
        {overlay}
        {inset}
      </div>
      {state !== "ready" && (
        <div className="stage-cover">
          {state === "checking" && <p>Unity 빌드를 찾는 중</p>}
          {state === "loading" && (
            <>
              <p>City Lab 불러오는 중 {Math.round(progress * 100)}%</p>
              <div className="bar"><span style={{ width: `${progress * 100}%` }} /></div>
            </>
          )}
          {state === "missing" && (
            <>
              <p>WebGL 빌드가 없습니다.</p>
              <p className="hint">
                Unity에서 TwinSight → Web → Build WebGL Demo를 실행하면 frontend/public/unity에 만들어집니다.
              </p>
            </>
          )}
          {state === "error" && <p>Unity를 시작하지 못했습니다: {error}</p>}
        </div>
      )}
    </div>
  );
}

function Lights({ status }: { status: UnityStatus | null }) {
  const light = status?.vehicle_light;
  const walk = status?.pedestrian_light;
  return (
    <div className="lights" aria-label="신호 상태">
      <div className="lamp-row" title="차량 신호">
        <span className={light === "red" ? "lamp red on" : "lamp red"} />
        <span className={light === "yellow" ? "lamp yellow on" : "lamp yellow"} />
        <span className={light === "green" ? "lamp green on" : "lamp green"} />
      </div>
      <div className="lights-text">
        <b>{!status ? "신호 정보 없음" : light ? `차량 ${light === "green" ? "초록" : light === "yellow" ? "노랑" : "빨강"}` : "실험 중 신호 고정"}</b>
        {!status ? null : light ? (
          <span>
            보행자 {walk === "green" ? "초록" : walk === "flashing_green" ? "초록 점멸" : "빨강"}
            {status?.signal_remaining != null && ` · ${Math.max(0, status.signal_remaining).toFixed(0)}초 남음`}
          </span>
        ) : (
          <span>사고를 치우면 신호가 다시 돌아갑니다</span>
        )}
      </div>
    </div>
  );
}

export function DemoPage() {
  const [status, setStatus] = useState<UnityStatus | null>(null);
  const [events, setEvents] = useState<(UnityEvent & { at: number })[]>([]);
  const [chosen, setChosen] = useState<ScenarioKey | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(
    () =>
      onUnityMessage((msg) => {
        if (msg.type === "ready") setConnected(true);
        else if (msg.type === "status") {
          setConnected(true);
          setStatus(msg);
        } else if (msg.type === "event") {
          setEvents((list) => [{ ...msg, at: Date.now() }, ...list].slice(0, 14));
        }
      }),
    [],
  );

  const mode = status?.mode ?? "sim";
  const night = status?.night ?? false;
  const current = SCENARIOS.find((s) => s.key === (chosen ?? status?.scenario));
  const [showReal, setShowReal] = useState(true);
  const real = realVideo(current?.key, status?.variant);
  const [detecting, setDetecting] = useState(false);
  const replayVideo = useRef<HTMLVideoElement>(null);
  const [caseKey, setCaseKey] = useState("pothole");
  const [replayDetect, setReplayDetect] = useState(false);
  const [videoAspect, setVideoAspect] = useState(16 / 9);
  const replayCase = CASES.find((c) => c.key === caseKey) ?? CASES[0];

  // 영상 재현: 실제 영상의 재생 시각을 Unity에 계속 알려 같은 장면을 맞춘다. 카메라가 바뀌는 영상은 쓰는 구간만 반복한다.
  useEffect(() => {
    if (mode !== "replay") return;
    const timer = window.setInterval(() => {
      const v = replayVideo.current;
      if (!v) return;
      if (replayCase.end !== undefined && v.currentTime > replayCase.end) v.currentTime = replayCase.start ?? 0;
      send("ReplaySync", `${v.currentTime.toFixed(3)}|${v.paused ? 0 : 1}`);
    }, 250);
    return () => window.clearInterval(timer);
  }, [mode, replayCase]);

  const liveReal = useLiveDetection(replayDetect && mode === "replay", replayVideo);
  const liveTwin = useLiveDetection(replayDetect && mode === "replay", undefined, "twin");

  const chooseCase = (key: string) => {
    const next = CASES.find((c) => c.key === key);
    if (!next || key === caseKey) return;
    setCaseKey(key);
    send("SetReplay", next.replay);
    // 사례를 바꾸면 이전 영상의 경고 목록과 백엔드 지속 상태를 지운다
    liveReal.clearAlerts();
    liveTwin.clearAlerts();
    fetch(`${API_BASE}/demo/reset?source=all`, { method: "POST" }).catch(() => undefined);
  };

  const live = useLiveDetection(detecting && mode === "sim");

  const toggleDetection = () => {
    const next = !detecting;
    setDetecting(next);
    // 모델이 학습한 조건: 가상 CCTV 시점, 차량 없음
    send("SetTraffic", next ? "0" : "1");
    send("SetCamera", next ? "cctv" : "incident");
    if (next) setShowReal(false);
  };

  // 검출 모드: 포트홀·낙하물을 가상 CCTV 가까이(x = DETECT_X) 만든다. 기본 위치(x = 12)는 너무 멀어 몇 픽셀로 보인다.
  const near = (cmd: string) => (detecting && /^(Pothole|Debris):/.test(cmd) ? `${cmd}@${DETECT_X}` : cmd);
  const trigger = (key: ScenarioKey) => {
    setChosen(key);
    if (detecting && key === "Pothole") send("SetVariant", near("Pothole:Wide"));
    else if (detecting && key === "FallingDebris") send("SetVariant", near("Debris:LargeBlock"));
    else send("SetScenario", key);
  };
  const triggerVariant = (key: ScenarioKey, cmd: string) => {
    setChosen(key);
    send("SetVariant", near(cmd));
  };

  // 검출 중에는 학습 조건(가상 CCTV, 차량 없음)을 유지한다. 다른 곳에서 바뀌면 되돌린다.
  useEffect(() => {
    if (!detecting || !status || status.mode !== "sim") return;
    if (status.camera !== "cctv") send("SetCamera", "cctv");
    if (status.traffic) send("SetTraffic", "0");
  }, [detecting, status?.camera, status?.traffic, status?.mode]);

  return (
    <main className="demo">
      <section className="demo-main">
        <div className="demo-bar">
          <div className="segmented" role="tablist" aria-label="화면">
            <button type="button" role="tab" aria-selected={mode === "sim"} onClick={() => send("SetMode", "sim")}>
              City Lab 사고 시나리오
            </button>
            <button type="button" role="tab" aria-selected={mode === "twin"} onClick={() => send("SetMode", "twin")}>
              금촌 CCTV 디지털 트윈
            </button>
            <button type="button" role="tab" aria-selected={mode === "replay"} onClick={() => send("SetMode", "replay")}>
              CCTV 영상 재현
            </button>
          </div>
          {mode === "sim" && (
            <div className="segmented small" aria-label="카메라">
              {CAMERAS.map((c) => (
                <button key={c.key} type="button" aria-pressed={status?.camera === c.key} onClick={() => send("SetCamera", c.key)}
                  disabled={detecting} title={detecting ? "모델 검출 중에는 학습 시점(가상 CCTV)으로 고정됩니다" : undefined}>
                  {c.label}
                </button>
              ))}
            </div>
          )}
          <div className="segmented small" aria-label="조명">
            <button type="button" aria-pressed={!night} onClick={() => send("SetNight", "0")}>주간</button>
            <button type="button" aria-pressed={night} onClick={() => send("SetNight", "1")}>야간</button>
          </div>
          {mode === "sim" && (
            <button type="button" className={detecting ? "detect-toggle on" : "detect-toggle"} aria-pressed={detecting}
              onClick={toggleDetection} disabled={!connected}>
              <i aria-hidden="true" />
              {detecting ? "모델 검출 중" : "모델 검출 켜기"}
            </button>
          )}
          {mode === "sim" && (
            <div className="segmented small" aria-label="실제 영상">
              <button type="button" aria-pressed={showReal} onClick={() => setShowReal((v) => !v)}>
                실제 CCTV 영상 {showReal ? "켬" : "끔"}
              </button>
            </div>
          )}
        </div>

        <div className={mode === "replay" ? "replay-pair" : "stage-wrap"}>
        {mode === "replay" && (
          <figure className="replay-real">
            <div className="video-box">
              <video key={replayCase.video} ref={replayVideo} src={replayCase.video} autoPlay muted loop playsInline controls
                onLoadedMetadata={(e) => {
                  const v = e.currentTarget;
                  if (v.videoWidth && v.videoHeight) setVideoAspect(v.videoWidth / v.videoHeight);
                  if (replayCase.start) v.currentTime = replayCase.start;
                }} />
              {replayDetect && liveReal.result && (
                <DetectionOverlay detections={liveReal.result.detections} width={liveReal.result.width} height={liveReal.result.height} />
              )}
            </div>
            <figcaption><b>실제 CCTV</b><span>{replayCase.caption}</span></figcaption>
          </figure>
        )}
        <UnityStage
          replay={mode === "replay"}
          aspect={mode === "replay" ? videoAspect : undefined}
          twin={mode === "twin" || (detecting && mode === "sim")}
          overlay={detecting && mode === "sim" && live.result ? (
            <DetectionOverlay detections={live.result.detections} width={live.result.width} height={live.result.height} />
          ) : mode === "replay" && replayDetect && liveTwin.result ? (
            <DetectionOverlay detections={liveTwin.result.detections} width={liveTwin.result.width} height={liveTwin.result.height} />
          ) : null}
          inset={
            mode === "sim" && showReal && real ? (
              <figure className="real-inset">
                <video key={real.src} src={real.src} autoPlay muted loop playsInline onError={() => setShowReal(false)} />
                <figcaption>
                  <b>실제 CCTV · {real.label}</b>
                  <span>{real.source}</span>
                </figcaption>
              </figure>
            ) : null
          }
        />
        </div>

        {mode === "twin" && (
          <div className="twin-strip">
            <div className="legend">
              <span><i className="sw orange" />Unity에 놓은 차량</span>
              <span><i className="sw green" />실제 CCTV의 YOLO 박스</span>
              <span>오른쪽 위: 같은 프레임의 실제 화면</span>
            </div>
            <div className="twin-controls">
              <button type="button" onClick={() => send("TwinStep", "-1")} aria-label="이전 프레임">이전</button>
              <b>
                프레임 {status ? status.twin_frame + 1 : "-"} / {status?.twin_frames || "-"} · 차량 {status?.twin_vehicles ?? 0}대
              </b>
              <button type="button" onClick={() => send("TwinStep", "1")} aria-label="다음 프레임">다음</button>
            </div>
          </div>
        )}
      </section>

      <aside className="demo-side">
        {mode === "sim" ? (
          <>
            <h2>사고 만들기</h2>
            <div className="signs">
              {SCENARIOS.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  className={status?.scenario === s.key ? "sign active" : "sign"}
                  onClick={() => trigger(s.key)}
                  disabled={!connected}
                  aria-label={`${s.name}: ${s.action}`}
                >
                  <SignIcon kind={s.key} />
                  <span className="sign-name">{s.name}</span>
                  <span className="sign-action">{s.action}</span>
                </button>
              ))}
            </div>
            {current && current.variants.length > 0 && (
              <div className="variants" aria-label={`${current.name} 변형`}>
                <span>{current.name} 변형</span>
                {current.variants.map((v) => (
                  <button
                    key={v.cmd}
                    type="button"
                    aria-pressed={status?.variant === v.cmd.split(":")[1]}
                    onClick={() => triggerVariant(current.key, v.cmd)}
                    disabled={!connected}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            )}
            <div className="side-row">
              <button type="button" className="plain" onClick={() => trigger("Normal")} disabled={!connected}>
                사고 치우고 정상 주행
              </button>
            </div>

            <Lights status={status} />

            {detecting && (
              <>
                <h2>모델 경고</h2>
                <p className="demo-note">
                  {live.error
                    ? live.error
                    : live.result
                      ? `가상 CCTV 화면을 초당 ${live.fps.toFixed(1)}장 검출 · 추론 ${Math.round(live.result.inference_ms)} ms · 박스 ${live.result.detections.length}개`
                      : "검출 서버에 첫 화면을 보내는 중"}
                </p>
                <ol className="model-alerts" aria-live="assertive">
                  {live.alerts.length === 0 && (
                    <li className="empty">이상 검출이 같은 자리에서 0.6초·3프레임 이상 이어지면 경고가 뜹니다.</li>
                  )}
                  {live.alerts.map((a) => (
                    <li key={a.alert_id}>
                      <b>{ALERT_KO[a.type] ?? a.type}</b>
                      <span>
                        {a.evidence.map((e) => `${CLASS_KO[e.class_name] ?? e.class_name} ${e.confidence.toFixed(2)}`).join(", ")} ·
                        미확인
                      </span>
                    </li>
                  ))}
                </ol>
              </>
            )}

            <h2>Unity 시나리오 기록</h2>
            <ol className="events" aria-live="polite">
              {events.length === 0 && <li className="empty">위 표지판을 누르면 Unity가 남기는 정답 기록이 여기에 쌓입니다.</li>}
              {events.map((e) => (
                <li key={`${e.episode}-${e.time}-${e.event_type}`} className={e.evidence === "physics_contact" ? "contact" : ""}>
                  <span className="t">{e.time.toFixed(1)}s</span>
                  {EVENT_TEXT[e.event_type] ?? e.event_type}
                </li>
              ))}
            </ol>

            <h2>{current && current.key !== "Normal" ? `${current.name} 모델 검증 결과` : "정상 신호 대기 검증"}</h2>
            {current && current.key !== "Normal" ? (
              <div className="verdict">
                {current.results.map((r) => (
                  <div key={r.label} className={r.ok ? "v ok" : "v warn"}><span>{r.label}</span><b>{r.text}</b></div>
                ))}
                <p>{current.model}. {current.note}</p>
              </div>
            ) : (
              <div className="verdict">
                <div className="v ok"><span>정상 대기 영상</span><b>24개</b></div>
                <div className="v ok"><span>불필요한 경고</span><b>0건</b></div>
                <p>주간·야간 정상 신호 대기 영상에서 확인한 결과입니다.</p>
              </div>
            )}
          </>
        ) : mode === "replay" ? (
          <>
            <h2>사고 영상 고르기</h2>
            <div className="variants" aria-label="재현할 사고 영상">
              {CASES.map((c) => (
                <button key={c.key} type="button" aria-pressed={c.key === caseKey} onClick={() => chooseCase(c.key)} disabled={!connected}>
                  {c.label}
                </button>
              ))}
            </div>
            <button type="button" className={replayDetect ? "detect-toggle on" : "detect-toggle"} aria-pressed={replayDetect}
              onClick={() => setReplayDetect((v) => !v)}>
              <i aria-hidden="true" />
              {replayDetect ? "양쪽 모델 검출 중" : "실제 영상·가상환경 함께 검출"}
            </button>
            <dl className="facts">
              <div><dt>재생 시각</dt><dd>{status ? `${status.replay_time.toFixed(1)} / ${status.replay_duration.toFixed(1)} s` : "-"}</dd></div>
              <div><dt>가상환경에 보이는 차량</dt><dd>{status?.replay_vehicles ?? 0}대</dd></div>
            </dl>
            {replayDetect && (
              <div className="alert-pair">
                {[{ title: "실제 CCTV 경고", live: liveReal }, { title: "가상환경 경고", live: liveTwin }].map(({ title, live: l }) => (
                  <section key={title}>
                    <h2>{title}</h2>
                    <p className="demo-note">{l.error || (l.result ? `박스 ${l.result.detections.length}개 · ${Math.round(l.result.inference_ms)} ms` : "검출 서버에 보내는 중")}</p>
                    <ol className="model-alerts" aria-live="polite">
                      {l.alerts.length === 0 && <li className="empty">같은 자리에서 0.6초·3프레임 이상 이어지면 경고</li>}
                      {l.alerts.map((a) => (
                        <li key={a.alert_id}>
                          <b>{ALERT_KO[a.type] ?? a.type}</b>
                          <span>{a.evidence.map((e) => `${CLASS_KO[e.class_name] ?? e.class_name} ${e.confidence.toFixed(2)}`).join(", ")}</span>
                        </li>
                      ))}
                    </ol>
                  </section>
                ))}
              </div>
            )}
            <p className="demo-note">
              오른쪽 가상환경은 왼쪽 영상에서 추정한 카메라(높이·각도·화각)와 차량 궤적으로 만든 같은 구도의 재현입니다.
              바닥·배경은 영상에서 차량을 지운 화면이고 차량은 3D 모델입니다. 실제 영상 검출 모델은 이 영상들의 앞 70 %
              구간으로 추가 학습했으므로(뒤 30 %로 검증), 처음 보는 CCTV에서의 성능을 뜻하지 않습니다.
            </p>
            {status?.replay_error && <p className="demo-note">{status.replay_error}</p>}
          </>
        ) : (
          <>
            <h2>실제 인식 결과를 가상환경으로</h2>
            <p className="lead">
              파주 금촌신사거리 CCTV에서 YOLO가 찾은 차량을 실제 도로 좌표(m)로 바꾸고, 같은 자세로 놓은 가상 CCTV
              앞에 다시 세웠습니다.
            </p>
            <dl className="facts">
              <div><dt>화면 위치 오차 중앙값</dt><dd>2.3 px</dd></div>
              <div><dt>박스 겹침(IoU) 중앙값</dt><dd>0.71</dd></div>
              <div><dt>차선 위치 오차(위성사진 대비)</dt><dd>0.17 m 이내</dd></div>
              <div><dt>캘리브레이션 오차(RMSE)</dt><dd>0.09 m</dd></div>
              <div><dt>카메라 높이</dt><dd>13.2 m</dd></div>
            </dl>
            <p className="demo-note">16프레임, 55대 기준. 길가 주차 차량과 화면 가장자리에 잘린 차량은 뺐습니다.</p>
          </>
        )}
        {!connected && <p className="demo-note">Unity가 준비되면 버튼이 켜집니다.</p>}
      </aside>
    </main>
  );
}
