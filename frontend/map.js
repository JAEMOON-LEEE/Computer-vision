/* Run-scoped map/history component. Text from the API is never interpreted as HTML. */
(() => {
  const api = window.TWINSIGHT_API;
  const select = document.getElementById("map-run");
  const status = document.getElementById("map-status");
  const local = document.getElementById("local-map");
  const riskList = document.getElementById("map-risk-list");
  let cameraId = null, cameraRows = [], generation = 0, request = 0;
  let snapshot = null, timer = null, nextOffset = null;
  let map = null, layers = null, fitNext = true;
  if (window.L) {
    map = L.map("road-map", {scrollWheelZoom: false}).setView([36.5, 127.5], 7);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    layers = L.featureGroup().addTo(map);
    new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById("road-map"));
  } else {
    document.getElementById("road-map").textContent = "지도 라이브러리를 불러오지 못했습니다. 지역 좌표와 이력은 아래에서 확인하세요.";
  }
  function text(value) {
    const el = document.createElement("span");
    el.textContent = value;
    return el;
  }
  function svg(tag, attrs, label) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
    if (label) { const title = document.createElementNS(el.namespaceURI, "title"); title.textContent = label; el.append(title); }
    local.append(el);
    return el;
  }
  async function json(path) {
    const response = await fetch(api + path);
    if (!response.ok) throw new Error(`이력 조회 실패 (${response.status})`);
    return response.json();
  }
  // Split at missing coordinates, non-increasing times, or >2 seconds without observations.
  function segments(points, coordinate) {
    const result = [];
    let part = [], previous = null;
    for (const point of points) {
      if (!point[coordinate] || (previous && (point.timestamp <= previous.timestamp || point.timestamp - previous.timestamp > 2))) {
        if (part.length) result.push(part);
        part = [];
      }
      if (point[coordinate]) part.push(point[coordinate]);
      previous = point;
    }
    if (part.length) result.push(part);
    return result;
  }
  function render() {
    local.replaceChildren(); riskList.replaceChildren();
    if (layers) layers.clearLayers();
    for (const camera of cameraRows) {
      if (!map || !Number.isFinite(camera.lat) || !Number.isFinite(camera.lon)) continue;
      L.circleMarker([camera.lat, camera.lon], {radius: camera.camera_id === cameraId ? 8 : 5, color: "#329bff"})
        .bindPopup(text(`CCTV: ${camera.name || camera.camera_id} (카메라 설치 위치)`))
        .on("click", () => window.dispatchEvent(new CustomEvent("map-camera", {detail: camera.camera_id}))).addTo(layers);
    }
    if (!snapshot) return;
    const risks = snapshot.risks.filter(r => document.getElementById("map-dismissed").checked || r.alert.status !== "dismissed");
    const all = snapshot.tracks.flatMap(t => t.points.filter(p => p.xz).map(p => p.xz))
      .concat(snapshot.untracked.map(p => p.xz), risks.flatMap(r => r.locations.map(p => p.xz)));
    const bounds = all.reduce((b, p) => [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])], [Infinity, Infinity, -Infinity, -Infinity]);
    const scale = all.length ? Math.min(720 / Math.max(bounds[2] - bounds[0], 1), 280 / Math.max(bounds[3] - bounds[1], 1)) : 1;
    const xy = p => [400 + (p[0] - (bounds[0] + bounds[2]) / 2) * scale, 180 - (p[1] - (bounds[1] + bounds[3]) / 2) * scale];
    if (all.length) {
      const label = svg("text", {x: 12, y: 22, fill: "#aebdce", "font-size": 13});
      label.textContent = `x ${bounds[0].toFixed(1)}…${bounds[2].toFixed(1)} / z ${bounds[1].toFixed(1)}…${bounds[3].toFixed(1)} (${snapshot.reference ? "m · ENU" : "입력 좌표 단위 미등록"})`;
    } else {
      const label = svg("text", {x: 40, y: 170, fill: "#aebdce"});
      label.textContent = "매핑된 노면 좌표가 없습니다. 픽셀 좌표로 경로를 만들지 않습니다.";
    }
    const mark = (point, color, label, radius = 4) => {
      if (point.xz) { const [cx, cy] = xy(point.xz); svg("circle", {cx, cy, r: radius, fill: color}, label); }
      if (map && point.latlon) L.circleMarker(point.latlon, {radius, color}).bindPopup(text(label)).addTo(layers);
    };
    for (const track of snapshot.tracks) {
      const label = `${track.class_name} / ${track.model_id} #${track.track_id}`;
      for (const part of segments(track.points, "xz")) {
        svg("polyline", {points: part.map(p => xy(p).join(",")).join(" "), fill: "none", stroke: "#3dde7a", "stroke-width": 2}, label);
      }
      if (map) for (const part of segments(track.points, "latlon")) {
        L.polyline(part, {color: "#259c51", weight: 3}).bindPopup(text(label)).addTo(layers);
      }
      const last = track.points[track.points.length - 1];
      if (last) mark(last, "#3dde7a", label);
    }
    for (const point of snapshot.untracked) mark(point, "#9aa6b5", `${point.class_name} · 추적 ID 없음`, 3);
    for (const risk of risks) {
      const a = risk.alert, color = a.severity === "critical" ? "#ff5d73" : "#ff9c38";
      const label = `#${a.id} ${a.type} · ${a.status} · frame ${a.frame}`;
      risk.locations.forEach(p => mark(p, color, label, 7));
      const item = document.createElement("li");
      item.textContent = `${label} — ${a.message} (${risk.locations.length ? "동일 프레임 근거 위치" : "위치 미확정"})`;
      riskList.append(item);
    }
    if (!risks.length) riskList.append(text("표시할 경고가 없습니다."));
    status.textContent = `프레임 ${snapshot.first_frame ?? "-"}–${snapshot.last_frame ?? "-"} · ${snapshot.timestamp_kind || "시간 기준 미등록"} · 경로 ${snapshot.tracks.length}개 · 매핑 없는 관측 ${snapshot.unmapped_detections}개. ` +
      (snapshot.reference ? "지역 ENU 기준으로 지도에 표시 (원점 반경 5km 이내). " : "지도 기준 미등록: 객체는 아래 지역 좌표로만 표시. ") +
      (snapshot.frames_truncated || snapshot.alerts_truncated ? "최근 일부 이력만 표시 중입니다. 전체 이력은 API로 조회하세요." : "");
    if (fitNext && map) {
      const selected = cameraRows.find(c => c.camera_id === cameraId);
      if (snapshot.reference) map.setView([snapshot.reference.origin_lat, snapshot.reference.origin_lon], 18);
      else if (selected && Number.isFinite(selected.lat) && Number.isFinite(selected.lon)) map.setView([selected.lat, selected.lon], 16);
      fitNext = false;
    }
  }
  async function refresh() {
    const token = ++request, epoch = generation, run = select.value;
    if (!run) { snapshot = null; render(); status.textContent = "이 카메라에 저장된 실행이 없습니다."; return; }
    try {
      const data = await json(`/runs/${encodeURIComponent(run)}/map`);
      if (token !== request || epoch !== generation || run !== select.value) return;
      snapshot = data; render();
    } catch (error) { if (token === request && epoch === generation) { snapshot = null; render(); status.textContent = error.message; } }
  }
  async function loadRuns(more = false) {
    const epoch = generation;
    try {
      const data = await json(`/runs?camera_id=${encodeURIComponent(cameraId)}&offset=${more ? nextOffset : 0}`);
      if (epoch !== generation) return;
      const selected = select.value;
      const selectedLabel = select.selectedOptions[0]?.textContent;
      if (!more) select.replaceChildren();
      for (const row of data.items) {
        if ([...select.options].some(o => o.value === row.run_id)) continue;
        const option = document.createElement("option"); option.value = row.run_id;
        option.textContent = `${row.run_id} · ${row.timestamp_kind || "시간 기준 미등록"}`; select.append(option);
      }
      // Keep an explicitly selected old run even when live refresh returns the newest page.
      if (selected && ![...select.options].some(o => o.value === selected)) {
        const option = document.createElement("option"); option.value = selected;
        option.textContent = selectedLabel; select.append(option);
      }
      if (selected) select.value = selected;
      nextOffset = data.next_offset; document.getElementById("map-more").hidden = nextOffset === null;
      await refresh();
    } catch (error) { if (epoch === generation) status.textContent = error.message; }
  }
  select.onchange = () => { fitNext = true; snapshot = null; render(); refresh(); };
  document.getElementById("map-refresh").onclick = () => loadRuns();
  document.getElementById("map-more").onclick = () => loadRuns(true);
  document.getElementById("map-dismissed").onchange = render;
  window.TwinSightMap = {
    cameras(rows) { cameraRows = rows; render(); },
    select(id) { cameraId = id; generation++; request++; clearTimeout(timer); timer = null; snapshot = null; select.replaceChildren(); fitNext = true; render(); loadRuns(); },
    event(message) {
      const eventCamera = message.camera_id || message.alert?.camera_id;
      if (eventCamera !== cameraId || timer) return;
      const epoch = generation;
      timer = setTimeout(() => { timer = null; if (epoch === generation) loadRuns(); }, 1000);
    },
  };
})();
