const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";
const DEFAULT_CAMERA = "its-cc4277cc18";

const COLORS = {
  car: "#3dde7a",
  person: "#4cc3ff",
  pothole: "#ff8a3d",
  crack: "#ffb020",
  debris: "#ff5d73",
  truck: "#8ea2ff",
  bus: "#c084fc",
  motorcycle: "#2dd4bf",
  bicycle: "#a3e635",
  barrier: "#f472b6",
};

const video = document.getElementById("video");
const canvas = document.getElementById("overlay");
const cameraList = document.getElementById("camera-list");
const alertList = document.getElementById("alert-list");
const logBox = document.getElementById("log");
const statusEl = document.getElementById("ws-status");
const cameraLabel = document.getElementById("camera-label");
const frameLabel = document.getElementById("frame-label");
const boxLabel = document.getElementById("box-label");

let cameras = [];
let selectedId = DEFAULT_CAMERA;
let hls = null;
let latestFrame = null;
let alerts = [];
let socket = null;

function log(message, isError) {
  const line = document.createElement("div");
  line.textContent = message;
  if (isError) line.className = "err";
  logBox.appendChild(line);
}

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

async function loadCameras() {
  const response = await fetch(API + "/cameras");
  if (!response.ok) throw new Error("카메라 목록 실패");
  cameras = await response.json();
  renderCameras();
}

function renderCameras() {
  const query = document.getElementById("camera-filter").value.trim().toLowerCase();
  const rows = cameras.filter((camera) => {
    const text = `${camera.camera_id} ${camera.name || ""} ${camera.source || ""}`.toLowerCase();
    return !query || text.includes(query);
  });
  cameraList.innerHTML = "";
  if (!rows.length) {
    cameraList.innerHTML = '<li class="empty">카메라가 없습니다. ID를 직접 재생할 수 있습니다.</li>';
  }
  for (const camera of rows) {
    const item = document.createElement("li");
    item.className = "camera" + (camera.camera_id === selectedId ? " active" : "");
    item.innerHTML = `<strong>${camera.name || camera.camera_id}</strong><small>${camera.camera_id} · ${camera.source || ""}</small>`;
    item.onclick = () => selectCamera(camera.camera_id);
    cameraList.appendChild(item);
  }
  if (!cameras.some((camera) => camera.camera_id === DEFAULT_CAMERA)) {
    const extra = document.createElement("li");
    extra.className = "camera" + (selectedId === DEFAULT_CAMERA ? " active" : "");
    extra.innerHTML = `<strong>${DEFAULT_CAMERA}</strong><small>기본 확인 카메라</small>`;
    extra.onclick = () => selectCamera(DEFAULT_CAMERA);
    cameraList.prepend(extra);
  }
}

async function selectCamera(cameraId) {
  selectedId = cameraId;
  latestFrame = null;
  activeRun = null;
  activeFrameNo = -1;
  droppedFrames = 0;
  cameraLabel.textContent = cameraId;
  frameLabel.textContent = "프레임 -";
  boxLabel.textContent = "박스 0";
  logBox.textContent = "";
  renderCameras();
  draw();
  await Promise.all([playStream(cameraId), loadAlerts(cameraId), loadLatest(cameraId)]);
}

async function playStream(cameraId) {
  if (hls) {
    hls.destroy();
    hls = null;
  }
  video.removeAttribute("src");
  video.load();
  let data;
  try {
    const response = await fetch(`${API}/cameras/${encodeURIComponent(cameraId)}/stream`);
    data = await response.json();
    if (!response.ok) {
      log("스트림 없음: " + (data.detail || response.status), true);
      return;
    }
  } catch (error) {
    log("백엔드에 연결하지 못했습니다. 서버와 이 페이지 주소(localhost:5173)를 확인하세요.", true);
    return;
  }
  log("스트림 받음 refreshed=" + data.refreshed);
  if (data.warning) log("경고: " + data.warning, true);
  if (window.Hls && Hls.isSupported()) {
    hls = new Hls();
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      log("영상 재생 시작");
      video.play().catch(() => {});
      draw();
    });
    hls.on(Hls.Events.ERROR, (_event, detail) => {
      log(`재생 오류: ${detail.type} ${detail.details} fatal=${detail.fatal}`, true);
    });
    hls.loadSource(data.stream_url);
    hls.attachMedia(video);
  } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = data.stream_url;
    log("브라우저 기본 HLS로 재생");
  } else {
    log("이 브라우저는 HLS를 재생하지 못합니다.", true);
  }
}

async function loadAlerts(cameraId) {
  const response = await fetch(`${API}/alerts?camera_id=${encodeURIComponent(cameraId)}&limit=50`);
  alerts = response.ok ? await response.json() : [];
  renderAlerts();
}

async function loadLatest(cameraId) {
  const response = await fetch(`${API}/cameras/${encodeURIComponent(cameraId)}/detections/latest`);
  if (!response.ok) return;
  const body = await response.json();
  latestFrame = {
    camera_id: body.camera_id,
    frame: body.frame,
    width: body.width,
    height: body.height,
    detections: body.detections,
  };
  draw();
}

function upsertAlert(alert) {
  if (alert.camera_id !== selectedId) return;
  const index = alerts.findIndex((item) => item.id === alert.id);
  if (index >= 0) alerts[index] = alert;
  else alerts.unshift(alert);
  alerts.sort((a, b) => b.timestamp - a.timestamp || b.id - a.id);
  renderAlerts();
}

function renderAlerts() {
  alertList.innerHTML = "";
  if (!alerts.length) {
    alertList.innerHTML = '<li class="empty">이 카메라의 경고가 없습니다.</li>';
    return;
  }
  for (const alert of alerts.slice(0, 40)) {
    const item = document.createElement("li");
    item.className = "alert";
    item.innerHTML = `<strong>${alert.type}</strong> · ${alert.status}<small>${alert.message}</small><small>#${alert.id} ${alert.alert_id} / frame ${alert.frame}</small>`;
    const actions = document.createElement("div");
    actions.className = "alert-actions";
    const confirm = document.createElement("button");
    confirm.className = "confirm";
    confirm.textContent = "확인";
    confirm.onclick = () => patchAlert(alert.id, "confirmed");
    const dismiss = document.createElement("button");
    dismiss.className = "dismiss";
    dismiss.textContent = "기각";
    dismiss.onclick = () => patchAlert(alert.id, "dismissed");
    actions.append(confirm, dismiss);
    item.appendChild(actions);
    alertList.appendChild(item);
  }
}

async function patchAlert(id, status) {
  const response = await fetch(`${API}/alerts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, handled_by: "dashboard" }),
  });
  if (!response.ok) {
    log("경고 상태 변경 실패", true);
    return;
  }
  upsertAlert(await response.json());
}

function contentRect() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const sourceWidth = video.videoWidth || (latestFrame && latestFrame.width) || 16;
  const sourceHeight = video.videoHeight || (latestFrame && latestFrame.height) || 9;
  const sourceRatio = sourceWidth / sourceHeight;
  const elementRatio = width / height || 1;
  if (elementRatio > sourceRatio) {
    const drawHeight = height;
    const drawWidth = height * sourceRatio;
    return { x: (width - drawWidth) / 2, y: 0, width: drawWidth, height: drawHeight };
  }
  const drawWidth = width;
  const drawHeight = width / sourceRatio;
  return { x: 0, y: (height - drawHeight) / 2, width: drawWidth, height: drawHeight };
}

// 여러 이벤트가 몰려도 화면에는 애니메이션 프레임당 한 번만 그린다(깜빡임 방지).
let paintRequested = false;
function draw() {
  if (paintRequested) return;
  paintRequested = true;
  requestAnimationFrame(() => {
    paintRequested = false;
    paint();
  });
}

// 캔버스 크기는 실제로 바뀌었을 때만 다시 잡는다. 크기를 다시 넣으면 캔버스가 지워진다.
function syncCanvasSize() {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { rect, ratio };
}

function paint() {
  const { rect, ratio } = syncCanvasSize();
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  if (!latestFrame || !latestFrame.detections) {
    frameLabel.textContent = "프레임 -";
    boxLabel.textContent = "박스 0";
    return;
  }
  const area = contentRect();
  const scaleX = area.width / latestFrame.width;
  const scaleY = area.height / latestFrame.height;
  context.lineWidth = 2;
  context.font = "13px Segoe UI, sans-serif";
  for (const detection of latestFrame.detections) {
    const box = detection.bbox_xyxy;
    if (!box || box.length !== 4) continue;
    const x = area.x + box[0] * scaleX;
    const y = area.y + box[1] * scaleY;
    const w = (box[2] - box[0]) * scaleX;
    const h = (box[3] - box[1]) * scaleY;
    const color = COLORS[detection.class_name] || "#ffffff";
    context.strokeStyle = color;
    context.strokeRect(x, y, w, h);
    const label = `${detection.class_name} #${detection.track_id ?? "-"} ${Number(detection.confidence).toFixed(2)}`;
    const textWidth = context.measureText(label).width;
    context.fillStyle = "rgba(0,0,0,0.65)";
    context.fillRect(x, Math.max(0, y - 18), textWidth + 8, 18);
    context.fillStyle = color;
    context.fillText(label, x + 4, Math.max(12, y - 5));
  }
  frameLabel.textContent = "프레임 " + latestFrame.frame;
  boxLabel.textContent = "박스 " + latestFrame.detections.length;
}

// 같은 카메라로 실행(run) 두 개가 동시에 들어오면 박스가 번갈아 그려져 깜빡인다.
// 지금 보고 있는 실행이 2초 넘게 조용할 때만 다른 실행으로 넘어간다.
// 실행 ID가 같아도(같은 목업을 두 번 켠 경우) 프레임 번호가 뒤로 가면 다른 흐름으로 보고 버린다.
let activeRun = null;
let activeRunSeenAt = 0;
let activeFrameNo = -1;
let droppedFrames = 0;
function acceptRun(runId, frameNo) {
  const now = performance.now();
  const quiet = now - activeRunSeenAt > 2000;
  if (activeRun === null || quiet || (runId === activeRun && frameNo > activeFrameNo)) {
    if (activeRun !== null && runId !== activeRun) log(`검출 실행 전환: ${activeRun} → ${runId}`);
    activeRun = runId;
    activeRunSeenAt = now;
    activeFrameNo = frameNo;
    return true;
  }
  droppedFrames += 1;
  if (droppedFrames === 1 || droppedFrames % 100 === 0) {
    log(`다른 검출 흐름이 같은 카메라로 들어오고 있어 무시합니다(${droppedFrames}건). 재생 창이 두 개 켜져 있는지 확인하세요.`, true);
  }
  return false;
}

function connectSocket() {
  socket = new WebSocket(WS_URL);
  socket.onopen = () => setStatus("실시간 연결됨", "on");
  socket.onclose = () => {
    setStatus("연결 끊김, 3초 후 재접속", "off");
    setTimeout(connectSocket, 3000);
  };
  socket.onerror = () => setStatus("연결 실패", "off");
  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    if (message.type === "detections" && message.camera_id === selectedId) {
      if (!acceptRun(message.run_id, Number(message.frame && message.frame.frame))) return;
      latestFrame = message.frame;
      draw();
    } else if ((message.type === "alert" || message.type === "alert_updated") && message.alert) {
      upsertAlert(message.alert);
    }
  };
}

document.getElementById("camera-filter").addEventListener("input", renderCameras);
video.addEventListener("loadedmetadata", draw);
new ResizeObserver(draw).observe(document.querySelector(".stage"));

document.getElementById("play").onclick = () => selectCamera(selectedId);

loadCameras()
  .catch(() => {
    log("백엔드에 연결하지 못했습니다.", true);
    renderCameras();
  })
  .finally(async () => {
    cameraLabel.textContent = selectedId;
    try {
      await loadAlerts(selectedId);
      await loadLatest(selectedId);
    } catch (_error) {
      log("경고·검출 조회에 실패했습니다.", true);
    }
  });
connectSocket();
