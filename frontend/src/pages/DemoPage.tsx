import { useEffect, useRef, useState } from "react";
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
import "../demo.css";

type ScenarioKey = "Normal" | "Pothole" | "FallingDebris" | "RoadsideDamage" | "Manhole";
type Verdict = { text: string; ok: boolean };

// 검증 결과는 2026-11 팀 보고 기준(합성 영상). Unity 화면의 사고는 시뮬레이션이며 모델 경고가 아니다.
const SCENARIOS: {
  key: ScenarioKey;
  name: string;
  action: string;
  warning: string;
  day: Verdict | null;
  night: Verdict | null;
  variants: { cmd: string; label: string }[];
}[] = [
  { key: "Pothole", name: "포트홀", action: "차로에 포트홀 만들기", warning: "road_damage",
    day: { text: "통과", ok: true }, night: { text: "통과", ok: true },
    variants: [
      { cmd: "Pothole:Small", label: "작은" }, { cmd: "Pothole:Wide", label: "넓은" },
      { cmd: "Pothole:Elongated", label: "길쭉한" }, { cmd: "Pothole:Cluster", label: "여러 개" },
    ] },
  { key: "FallingDebris", name: "낙하물", action: "콘크리트 낙하물 떨어뜨리기", warning: "road_debris",
    day: { text: "통과", ok: true }, night: { text: "통과", ok: true },
    variants: [
      { cmd: "Debris:SmallBlock", label: "작은 블록" }, { cmd: "Debris:LargeBlock", label: "큰 블록" },
      { cmd: "Debris:FlatSlab", label: "판재" }, { cmd: "Debris:MultipleBlocks", label: "여러 개" },
    ] },
  { key: "RoadsideDamage", name: "시설물 파손", action: "시선유도봉·가드레일 파손", warning: "",
    day: null, night: null,
    variants: [
      { cmd: "Roadside:Delineators", label: "시선유도봉 쓰러짐" }, { cmd: "Roadside:GuardrailBent", label: "가드레일 휨" },
      { cmd: "Roadside:GuardrailBroken", label: "가드레일 떨어짐" },
    ] },
  { key: "Manhole", name: "맨홀", action: "맨홀 뚜껑 이상", warning: "",
    day: null, night: null,
    variants: [
      { cmd: "Manhole:Open", label: "뚜껑 열림" }, { cmd: "Manhole:Raised", label: "뚜껑 들뜸" },
      { cmd: "Manhole:Sunken", label: "주변 침하" },
    ] },
];

const EVENT_TEXT: Record<string, string> = {
  episode_started: "시나리오 시작",
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

function UnityStage({ twin }: { twin: boolean }) {
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
    <div className={twin ? "stage twin" : "stage"}>
      <div ref={host} className="stage-canvas" />
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

  const trigger = (key: ScenarioKey) => {
    setChosen(key);
    send("SetScenario", key);
  };
  const triggerVariant = (key: ScenarioKey, cmd: string) => {
    setChosen(key);
    send("SetVariant", cmd);
  };

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
          </div>
          {mode === "sim" && (
            <div className="segmented small" aria-label="카메라">
              {CAMERAS.map((c) => (
                <button key={c.key} type="button" aria-pressed={status?.camera === c.key} onClick={() => send("SetCamera", c.key)}>
                  {c.label}
                </button>
              ))}
            </div>
          )}
          <div className="segmented small" aria-label="조명">
            <button type="button" aria-pressed={!night} onClick={() => send("SetNight", "0")}>주간</button>
            <button type="button" aria-pressed={night} onClick={() => send("SetNight", "1")}>야간</button>
          </div>
        </div>

        <UnityStage twin={mode === "twin"} />

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
            {current && current.key !== "Normal" && current.day && current.night ? (
              <div className="verdict">
                <div className={current.day.ok ? "v ok" : "v warn"}><span>주간</span><b>{current.day.text}</b></div>
                <div className={current.night.ok ? "v ok" : "v warn"}><span>야간</span><b>{current.night.text}</b></div>
                <p>경고 종류 {current.warning}. 합성 영상에서 검출 모델과 추적 기반 경고 규칙으로 확인한 결과입니다.</p>
              </div>
            ) : current && current.key !== "Normal" ? (
              <p className="demo-note">검출 모델이 아직 학습하지 않은 위험입니다. 가상환경 시연 장면이며 경고 검증 결과는 없습니다.</p>
            ) : (
              <div className="verdict">
                <div className="v ok"><span>정상 대기 영상</span><b>24개</b></div>
                <div className="v ok"><span>불필요한 경고</span><b>0건</b></div>
                <p>주간·야간 정상 신호 대기 영상에서 확인한 결과입니다.</p>
              </div>
            )}
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
