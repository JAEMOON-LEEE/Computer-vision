import { useEffect, useRef, useState } from "react";
import { alertLabels, classLabels, clock, labRequest, validCrop, youtubeReference } from "../lab";
import type { LabAlert, LabFrame, LabSession, SourceKind } from "../lab";
import "./validationLab.css";
import { API_BASE } from "../api";

type Result = LabFrame & { image: string; modelLabel: string };
type RunOptions = { kind: SourceKind; precise: boolean; fps: number; end: number; crop: number[]; modelLabel: string };

export function ValidationLab() {
  const [kind, setKind] = useState<SourceKind | null>(null);
  const [objectUrl, setObjectUrl] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [youtubeText, setYoutubeText] = useState("");
  const [youtube, setYoutube] = useState<ReturnType<typeof youtubeReference>>(null);
  const [model, setModel] = useState("real-coco");
  const [collisionV2Ready,setCollisionV2Ready]=useState(false);
  const [realTrafficReady,setRealTrafficReady]=useState(false);
  const [realCocoReady,setRealCocoReady]=useState(false);
  const [realSceneReady,setRealSceneReady]=useState(false);
  const [realScene,setRealScene]=useState(false);
  const [simulationPolicy,setSimulationPolicy]=useState(false);
  const [confidence, setConfidence] = useState(.25);
  const [fixed, setFixed] = useState(false);
  const [precise, setPrecise] = useState(true);
  const [fps, setFps] = useState(5);
  const [crop, setCrop] = useState([0, 0, 100, 100]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [phase, setPhase] = useState<"off" | "loading" | "on">("off");
  const [result, setResult] = useState<Result | null>(null);
  const [alerts, setAlerts] = useState<LabAlert[]>([]);
  const [frames, setFrames] = useState(0);
  const [alertTotal, setAlertTotal] = useState(0);
  const [message, setMessage] = useState("영상이나 사진을 선택한 뒤 원하는 장면에서 모델을 켜세요.");
  const [error, setError] = useState("");
  const [expected, setExpected] = useState("unspecified");
  const [judgment, setJudgment] = useState("unreviewed");
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState("");
  const [clientId] = useState(() => {
    try {
      const key = "twinsight-lab-client";
      const existing = sessionStorage.getItem(key);
      if (existing) return existing;
      const id = crypto.randomUUID(); sessionStorage.setItem(key, id); return id;
    } catch { return crypto.randomUUID(); }
  });
  const video = useRef<HTMLVideoElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const generation = useRef(0);
  const active = useRef<LabSession | null>(null);
  const lastSession = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const automaticSeek = useRef(false);
  const captureStarted = useRef(0);
  const currentUrl = useRef("");
  const currentStream = useRef<MediaStream | null>(null);
  const runOptions = useRef<RunOptions | null>(null);
  const alive = useRef(true);

  function stopModel(note = "모델 OFF · 영상 재생은 직접 조작할 수 있습니다.") {
    generation.current += 1;
    window.clearTimeout(timer.current);
    const previous = active.current;
    active.current = null;
    if (alive.current) { setPhase("off"); if (note) setMessage(note); }
    if (previous) void labRequest(`sessions/${previous.session_id}/stop`, {}).catch(() => undefined);
  }

  useEffect(() => {
    alive.current = true;
    const previousTitle = document.title;
    document.title = "TwinSight 영상 검증";
    const release = () => { if (active.current) navigator.sendBeacon(`${API_BASE}/lab/sessions/${active.current.session_id}/stop`); };
    window.addEventListener("pagehide", release);
    return () => {
      window.removeEventListener("pagehide", release);
      document.title = previousTitle;
      alive.current = false;
      stopModel("");
      currentStream.current?.getTracks().forEach(track => track.stop());
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    };
  }, []);

  useEffect(()=>{
    let mounted=true;
    const check=async()=>{
      try {const response=await fetch(`${API_BASE}/lab/health`);const health=await response.json();
        if(mounted){setCollisionV2Ready(health.collision_v2_ready===true);setRealTrafficReady(health.real_traffic_ready===true);setRealCocoReady(health.real_coco_ready===true);setRealSceneReady(health.real_incident_ready===true);}
      } catch { /* Existing API errors remain visible when starting a session. */ }
    };
    void check();const poll=window.setInterval(()=>void check(),15000);
    return()=>{mounted=false;window.clearInterval(poll);};
  },[]);

  useEffect(() => {
    if (video.current) {
      video.current.srcObject = kind === "screen" ? stream : null;
      if (kind === "screen" && stream) void video.current.play().catch(() => undefined);
    }
  }, [kind, stream, objectUrl]);

  function clearSource() {
    stopModel("");
    currentStream.current?.getTracks().forEach(track => track.stop());
    currentStream.current = null;
    setStream(null);
    if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    currentUrl.current = "";
    setResult(null); setAlerts([]); setFrames(0); setAlertTotal(0); setSaved(""); setError("");
    lastSession.current = null;
    setStart(""); setEnd("");
    setFixed(false); setSimulationPolicy(false); setCrop([0, 0, 100, 100]);
  }

  function chooseFile(file?: File) {
    if (!file) return;
    if (!file.type.startsWith("video/") && !file.type.startsWith("image/")) { setError("영상 또는 이미지 파일을 선택해 주세요."); return; }
    clearSource();
    const url = URL.createObjectURL(file);
    currentUrl.current = url; setObjectUrl(url); setSourceLabel(file.name);
    setKind(file.type.startsWith("image/") ? "image" : "video");
    setMessage("준비되었습니다. 사고 전 3초 이상을 포함해 모델을 켜세요. 사진은 객체 검출만 확인합니다.");
  }

  async function connectScreen() {
    try {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error("화면 공유는 Chrome/Edge의 localhost 또는 HTTPS에서 이용해 주세요.");
      const chosen = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 10 }, audio: false });
      clearSource();
      currentStream.current = chosen; setStream(chosen); setKind("screen"); setObjectUrl("");
      setSourceLabel(chosen.getVideoTracks()[0].label || "사용자가 공유한 화면");
      captureStarted.current = performance.now();
      chosen.getVideoTracks()[0].onended = () => { stopModel("화면 공유가 종료되어 모델을 껐습니다."); setStream(null); setKind(null); };
      setMessage("공유 화면 연결 완료. 재생·일시정지·장면 전환 후에는 모델 OFF → ON으로 추적 이력을 초기화해 주세요.");
    } catch (e) { setError(e instanceof Error ? e.message : "화면 공유를 연결하지 못했습니다."); }
  }

  async function seekTo(time: number) {
    const element = video.current;
    if (!element || Math.abs(element.currentTime-time) < .001) return;
    automaticSeek.current = true;
    try {
      await new Promise<void>((resolve, reject) => {
        const deadline = window.setTimeout(() => { cleanup(); reject(new Error("영상 위치 이동 시간이 초과되었습니다.")); }, 5000);
        const finish = () => { cleanup(); resolve(); };
        const cleanup = () => { window.clearTimeout(deadline); element.removeEventListener("seeked", finish); };
        element.addEventListener("seeked", finish, { once: true });
        element.currentTime = time;
      });
    } finally { automaticSeek.current = false; }
  }

  function snapshot(roi: number[]) {
    const source = kind === "image" ? image.current : video.current;
    if (!source) throw new Error("입력 화면이 없습니다.");
    const width = source instanceof HTMLVideoElement ? source.videoWidth : source.naturalWidth;
    const height = source instanceof HTMLVideoElement ? source.videoHeight : source.naturalHeight;
    if (!width || !height) throw new Error("영상·이미지 로딩이 끝난 뒤 다시 시도해 주세요.");
    const [x, y, w, h] = roi.map((value, index) => value/100 * (index%2 === 0 ? width : height));
    const scale = Math.min(1, 1280/Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w*scale)); canvas.height = Math.max(1, Math.round(h*scale));
    canvas.getContext("2d")!.drawImage(source, x, y, w, h, 0, 0, canvas.width, canvas.height);
    return { image: canvas.toDataURL("image/jpeg", .88), timestamp: kind === "screen" ? (performance.now()-captureStarted.current)/1000 : kind === "image" ? 0 : video.current!.currentTime };
  }

  async function startModel(single = false) {
    if (!kind || phase !== "off") return;
    if (!validCrop(crop)) { setError("분석 영역은 X+너비, Y+높이가 100% 안에 들어가야 합니다."); return; }
    setError(""); setSaved(""); setPhase("loading");
    const token = ++generation.current;
    const options: RunOptions = { kind, precise: !single && kind === "video" && precise, fps, crop: [...crop],
      end: kind === "video" ? Math.min(end === "" ? Infinity : Number(end), video.current?.duration || Infinity) : Infinity,
      modelLabel: (model === "real-coco" ? "실제 영상 범용 모델" : model === "real-traffic" ? "실제 CCTV 보강 모델" : model === "collision-v2" ? "충돌 보강 주간·야간 모델" : model === "day-night" ? "이전 주간·야간 모델" : "이전 주간 비교 모델")
        +(!single&&simulationPolicy?" · 가상 충돌 판정":"") };
    runOptions.current = options;
    let session: LabSession | null = null;
    try {
      if (options.precise) {
        video.current!.pause();
        await seekTo(start === "" ? video.current!.currentTime : Number(start));
        if (options.end <= video.current!.currentTime) throw new Error("구간 끝은 시작보다 뒤여야 합니다.");
      }
      session = await labRequest<LabSession>("sessions", { model, confidence, source_kind: single ? "image" : kind,
        source_label: sourceLabel, reference_url: youtube?.url || "", fixed_camera: fixed, crop_percent: crop,
        simulation_collision_policy: !single && kind!=="image" && simulationPolicy,
        real_incident_scene: !single && kind!=="image" && realScene,
        client_id: clientId, sampling_fps: fps, sampling_mode: single || kind === "image" ? "single" : options.precise ? "source_clock_steps" : "realtime" });
      if (token !== generation.current || !alive.current) { await labRequest(`sessions/${session.session_id}/stop`, {}); return; }
      active.current = session; lastSession.current = session.session_id; setPhase("on");
      setFrames(0); setAlerts([]); setAlertTotal(0);
      setMessage(single || kind === "image" ? "한 장 객체 검출 · 사진만으로 사고 여부를 판정하지 않습니다." : options.precise ? "정밀 구간 분석 · 처리 속도와 무관하게 원본 시각으로 순서대로 검사합니다." : "재생 화면을 분석 중입니다. 사고 전후 연속 장면을 유지해 주세요.");
      const iterate = async () => {
        if (token !== generation.current || !active.current) return;
        try {
          const begun = performance.now();
          const shot = snapshot(options.crop);
          const frame = await labRequest<LabFrame>(`sessions/${session!.session_id}/frames`, { image_b64: shot.image, timestamp: shot.timestamp, request_id: `${token}-${shot.timestamp}` });
          if (token !== generation.current || !alive.current) return;
          setResult({ ...frame, image: shot.image, modelLabel: options.modelLabel });
          setFrames(value => value+1);
          if (frame.alerts.length) { setAlerts(value => [...frame.alerts, ...value].slice(0, 50)); setAlertTotal(value => value+frame.alerts.length); }
          if (single || options.kind === "image") { stopModel("한 장 검출 완료 · 모델 OFF"); return; }
          if (options.precise) {
            const next = shot.timestamp+1/options.fps;
            if (next > options.end || next >= video.current!.duration-.02) { stopModel("지정 구간 분석 완료 · 모델 OFF"); return; }
            await seekTo(next);
          } else if (options.kind === "video" && (video.current!.paused || video.current!.ended)) {
            stopModel("재생이 멈춰 모델을 껐습니다. 다음 구간에서 다시 켜세요."); return;
          }
          if (token === generation.current) timer.current = window.setTimeout(() => void iterate(), options.precise ? 0 : Math.max(0, 1000/options.fps-(performance.now()-begun)));
        } catch (e) {
          if (token !== generation.current) return;
          stopModel(""); setError(e instanceof Error ? e.message : "분석 중 오류가 발생했습니다.");
        }
      };
      void iterate();
    } catch (e) {
      if (token === generation.current) { stopModel(""); setError(e instanceof Error ? e.message : "모델을 시작하지 못했습니다."); }
      else if (session) void labRequest(`sessions/${session.session_id}/stop`, {}).catch(() => undefined);
    }
  }

  async function saveReport() {
    if (!lastSession.current) return;
    try {
      const savedReport = await labRequest<{ path: string }>(`sessions/${lastSession.current}/report`, { expected_case: expected, judgment, notes });
      setSaved(savedReport.path); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "결과 저장 실패"); }
  }

  const locked = phase !== "off";
  return <main className="validation-lab">
    <div className="lab-heading"><div><span className="lab-eyebrow">MANUAL VALIDATION</span><h1>원하는 장면에서 모델 확인</h1><p>사고·낙하물 사례를 재생하고, 직접 모델을 켜고 끄며 결과를 비교하세요.</p></div><span className={`lab-state ${phase}`}>{phase === "on" ? "● 모델 ON" : phase === "loading" ? "모델 준비 중…" : "○ 모델 OFF"}</span></div>
    <div className="lab-method"><strong>사례 확인용 실험실</strong><span>사진은 객체 검출만, 추돌은 사고 전후 연속 영상으로 확인합니다. 선택한 장면의 결과는 실제 CCTV 정확도가 아닙니다.</span></div>
    <section className="lab-youtube lab-card"><div className="lab-section-title"><h2>1. 영상 준비</h2><span>유튜브는 공식 플레이어로 참고 재생</span></div>
      <div className="lab-url"><input aria-label="유튜브 주소" placeholder="https://www.youtube.com/watch?v=..." value={youtubeText} onChange={e => setYoutubeText(e.target.value)} /><button onClick={() => { const parsed = youtubeReference(youtubeText); if (!parsed) setError("올바른 유튜브 영상 주소를 입력해 주세요."); else { if (kind === "screen") stopModel("참고 영상을 바꿔 모델을 껐습니다. 새 장면에서 다시 켜세요."); setYoutube(parsed); setError(""); } }}>유튜브 열기</button></div>
      {youtube && <div className="lab-youtube-player"><iframe title="YouTube 참고 영상" src={`https://www.youtube-nocookie.com/embed/${youtube.id}?start=${youtube.start}&rel=0`} allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" /><a href={youtube.url} target="_blank" rel="noreferrer">별도 탭에서 재생 ↗</a><button onClick={() => { if (kind === "screen") stopModel(); setYoutube(null); }}>참고 영상 닫기</button></div>}
      <div className="lab-source-actions"><label className="lab-file-button">영상·사진 파일 선택<input type="file" accept="video/*,image/*" aria-label="영상 또는 사진 파일" onChange={e => { chooseFile(e.target.files?.[0]); e.currentTarget.value = ""; }} /></label><button onClick={() => void connectScreen()}>화면 연결</button>{kind === "screen" && <button onClick={() => { clearSource(); setKind(null); setSourceLabel(""); setMessage("화면 연결 해제 · 모델 OFF"); }}>화면 연결 해제</button>}<span>분석할 권한이 있는 화면·파일을 선택하세요. 화면 공유 선택창은 직접 조작해야 합니다.</span></div>
    </section>
    <div className="lab-columns"><section className="lab-card"><div className="lab-section-title"><h2>2. 입력 화면</h2><span>{kind === "screen" ? "공유 시각 · 사례 확인 전용" : kind === "image" ? "사진 · 객체 검출" : "영상 · 원본 재생 시각"}</span></div>
      <div className="lab-media">{kind === "image" ? <img ref={image} src={objectUrl} alt="선택한 분석 이미지" /> : kind ? <video ref={video} src={kind === "video" ? objectUrl : undefined} controls={kind === "video"} muted playsInline onSeeking={() => { if (active.current && !automaticSeek.current) stopModel("영상 위치가 바뀌어 모델 OFF · 새 구간에서 다시 켜세요."); }} onPlay={() => { if (active.current && kind === "video" && runOptions.current?.precise) stopModel("수동 재생을 시작해 정밀 검사를 껐습니다."); }} onPause={() => { if (active.current && kind === "video" && !runOptions.current?.precise) stopModel("영상 일시정지 · 모델 OFF"); }} /> : <div className="lab-empty"><span>▶</span><strong>분석할 화면을 연결하세요</strong><p>파일을 선택하거나, 재생 중인 탭·창을 공유할 수 있습니다.</p></div>}</div><p className="lab-source-name">{sourceLabel || "입력 없음"}</p>
      <div className="lab-settings"><label>모델<select value={model} disabled={locked} onChange={e => {setModel(e.target.value);setSimulationPolicy(false);setRealScene(false);}}><option value="real-coco" disabled={!realCocoReady}>{realCocoReady?"실제 영상 범용 모델 · 트럭·버스 포함":"범용 차량 모델 · 파일 확인 중"}</option><option value="real-traffic" disabled={!realTrafficReady}>{realTrafficReady?"실제 CCTV 보강 모델 · 추가 학습":"실제 CCTV 모델 · 학습·비교 확인 중"}</option><option value="collision-v2" disabled={!collisionV2Ready}>{collisionV2Ready?"충돌 보강 주간·야간 모델":"충돌 보강 모델 · 학습·검사 준비 중"}</option><option value="day-night">이전 주간·야간 모델</option><option value="day">이전 주간 비교 모델</option></select></label><label>검출 신뢰도<input type="number" min="0.05" max="0.95" step="0.05" value={confidence} disabled={locked} onChange={e => setConfidence(Number(e.target.value))} /></label><label>초당 검사 수<select value={fps} disabled={locked} onChange={e => { setFps(Number(e.target.value)); if (Number(e.target.value) < 4) {setFixed(false);setSimulationPolicy(false);setRealScene(false);} }}><option value="2">2장 · 객체 확인</option><option value="5">5장</option><option value="8">8장</option></select></label></div>
      {(model==="real-traffic" || model==="real-coco") && <p className="lab-footnote">승용차·트럭·버스·보행자·오토바이·자전거를 확인합니다. 도로 파임·낙하물·구조물은 이 모델의 검출 대상에 포함되지 않습니다.</p>}
      <label className="lab-check"><input type="checkbox" checked={fixed} disabled={locked || kind === "image" || fps < 4} onChange={e => {setFixed(e.target.checked);if(!e.target.checked){setSimulationPolicy(false);setRealScene(false);}}} />고정 카메라 영상입니다 — 충돌 의심 경고도 확인</label>
      {!fixed && kind!=="image" && <p className="lab-footnote">현재 충돌 경고는 꺼져 있습니다. 고정 CCTV는 위 항목을 선택하고 사고 전부터 재생해 주세요.</p>}
      {(model==="real-traffic" || model==="real-coco") && <><label className="lab-check"><input type="checkbox" checked={realScene} disabled={locked || !fixed || kind==="image" || fps<5 || !realSceneReady} onChange={e=>setRealScene(e.target.checked)} />실제 사고 장면 후보 분류 · 실험</label><p className="lab-footnote">실제 사고·정상 영상으로 학습한 장면 분류입니다. 시험32영상에서 사고9/16, 정상 영상 오경고3/16으로 수동 검사에만 사용하세요. 정확한 충돌 순간·대상을 확정하지 않으며 처리 시간이 추가됩니다.</p></>}
      {model==="collision-v2" && <label className="lab-check"><input type="checkbox" checked={simulationPolicy} disabled={locked || !fixed || kind==="image" || fps<5 || !collisionV2Ready} onChange={e=>setSimulationPolicy(e.target.checked)} />가상 CCTV 전용 충돌 판정 사용 · 실제 CCTV 성능 미검증</label>}
      {kind === "video" && <div className="lab-precision"><label className="lab-check"><input type="checkbox" checked={precise} disabled={locked} onChange={e => setPrecise(e.target.checked)} />정밀 구간 검사 · 원본 시간을 따라 한 장씩 진행</label><div className="lab-range"><label>시작(초)<input type="number" min="0" step="0.2" placeholder="현재 위치" disabled={locked} value={start} onChange={e => setStart(e.target.value)} /></label><label>끝(초)<input type="number" min="0" step="0.2" placeholder="영상 끝" disabled={locked} value={end} onChange={e => setEnd(e.target.value)} /></label></div></div>}
      <details className="lab-roi"><summary>분석 영역 설정 · 영상 바깥·자막 제외</summary><div className="lab-crop">{["X(%)", "Y(%)", "너비(%)", "높이(%)"].map((label, index) => <label key={label}>{label}<input type="number" min="0" max="100" value={crop[index]} disabled={locked} onChange={e => setCrop(value => value.map((v, i) => i === index ? Number(e.target.value) : v))} /></label>)}</div><p>선택한 영역을 전체 입력으로 분석합니다. Unity 전용 원거리 영역·정지선 좌표는 적용하지 않습니다.</p></details>
      <div className="lab-model-actions"><button className={phase === "on" ? "lab-off" : "lab-primary"} disabled={!kind || phase === "loading"} onClick={() => phase === "on" ? stopModel() : void startModel()}>{phase === "on" ? "모델 끄기" : phase === "loading" ? "모델 불러오는 중…" : "모델 켜기"}</button><button disabled={!kind || locked} onClick={() => void startModel(true)}>현재 한 장만 검사</button><button disabled={phase !== "loading"} onClick={() => stopModel("시작 요청 취소 · 모델 OFF")}>시작 취소</button></div>
    </section>
    <section className="lab-card"><div className="lab-section-title"><h2>3. 인식 결과</h2><span>{result ? `${result.modelLabel} · ${clock(result.timestamp)}` : "분석한 프레임에만 표시"}</span></div>
      <div className="lab-result">{result ? <svg viewBox={`0 0 ${result.width} ${result.height}`} role="img" aria-label="모델 검출 결과"><image href={result.image} width={result.width} height={result.height} />{result.detections.map((d, index) => { const [x1, y1, x2, y2] = d.bbox_xyxy; const color = ["debris", "pothole", "barrier"].includes(d.class_name) ? "#ffb347" : "#46edb5"; return <g key={index}><rect x={x1} y={y1} width={x2-x1} height={y2-y1} fill="none" stroke={color} strokeWidth={Math.max(2, result.width/450)} /><text x={x1} y={Math.max(16, y1-5)} fill={color} stroke="#111" strokeWidth=".5" fontSize={Math.max(14, result.width/65)}>{classLabels[d.class_name] || d.class_name} {Math.round(d.confidence*100)}%</text></g>; })}</svg> : <div className="lab-empty"><span>⌖</span><strong>모델을 켜면 결과가 표시됩니다</strong><p>처리한 원본 프레임 위에 검출 박스를 표시합니다.</p></div>}</div>
      <div className="lab-stats"><div><span>검사 프레임</span><strong>{frames}</strong></div><div><span>현재 객체</span><strong>{result?.detections.length || 0}</strong></div><div><span>의심 경고</span><strong>{alertTotal}</strong></div><div><span>추론 시간</span><strong>{result ? `${Math.round(result.inference_ms)}ms` : "—"}</strong></div></div>
      <div className="lab-detections">{result?.detections.map((d, index) => <span key={index}>{classLabels[d.class_name] || d.class_name} · {Math.round(d.confidence*100)}%</span>)}</div>
      <h3>경고 기록</h3><div className="lab-alerts">{alerts.length ? alerts.map((a, index) => <div key={index}><strong>{alertLabels[a.type] || a.type}</strong><time>{clock(a.timestamp)}</time><p>모델이 관측한 의심 상황입니다. 원본 영상과 함께 확인하세요.</p></div>) : <p>현재 경고가 없습니다. 경고 0건이 정상 장면이나 사고 없음의 증명은 아닙니다.</p>}</div>
    </section></div>
    <div className="lab-notice" role="status">{message}</div>{error && <div className="lab-error" role="alert">{error}</div>}
    <section className="lab-card lab-review"><div className="lab-section-title"><h2>4. 직접 판정하고 결과 보관</h2><span>입력 프레임은 서버에 저장하지 않습니다</span></div><div className="lab-review-fields"><label>확인할 상황<select value={expected} onChange={e => setExpected(e.target.value)}>{[["unspecified", "미지정"], ["normal", "정상 대기·주행"], ["pothole", "포트홀"], ["debris", "낙하물"], ["rear_end", "차량 추돌"], ["structure_impact", "구조물 충돌"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label><label>직접 확인 결과<select value={judgment} onChange={e => setJudgment(e.target.value)}>{[["unreviewed", "아직 미검토"], ["detected", "원하는 대상·상황을 인식함"], ["missed", "놓친 대상·상황이 있음"], ["false_alarm", "오탐·불필요한 경고"], ["normal", "정상 장면 확인"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label><label>메모<textarea value={notes} onChange={e => setNotes(e.target.value)} placeholder="사고 시각, 가림·야간·자막 여부 등을 적어 주세요." /></label></div><button onClick={() => void saveReport()} disabled={!lastSession.current}>결과를 D드라이브에 저장</button>{saved && <p className="lab-saved">저장 완료: <code>{saved}</code></p>}<p className="lab-footnote">사진에서 구조물이 보이는 것과 구조물이 떨어지는 사건을 인식하는 것은 다릅니다. 현재 모델은 일반적인 낙하 동작·붕괴 전용 모델이 아니며, 사고 경고는 실험 단계입니다.</p></section>
  </main>;
}
