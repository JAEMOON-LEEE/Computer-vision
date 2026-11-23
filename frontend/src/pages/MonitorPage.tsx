import { useEffect, useMemo, useState } from "react";
import { getDetectionStats, getLatest } from "../api";
import { CameraMap } from "../components/CameraMap";
import { CameraPanel } from "../components/CameraPanel";
import { FilterSidebar } from "../components/FilterSidebar";
import { LatencyPanel } from "../components/LatencyPanel";
import { RiskEventTable } from "../components/RiskEventTable";
import { useLive } from "../live";
import {
  DEFAULT_FILTERS,
  isOffline,
  periodRange,
  matchesAlertCount,
  splitPlace,
  summarize,
  type Filters,
} from "../mapModel";
import { RISK_THEME, riskLevel } from "../risk";
import { objectsForCamera, passesRisk, riskEvents } from "../twinModel";
import type { Camera, DetectionStats, OverlayState } from "../types";

type SortKey = "alerts" | "recent";

const statsCache = new Map<string, { at: number; stats: DetectionStats }>();

export function MonitorPage() {
  const live = useLive();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [draft, setDraft] = useState<Filters>(DEFAULT_FILTERS);
  const [applied, setApplied] = useState<Filters>(DEFAULT_FILTERS);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("alerts");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [visibleIds, setVisibleIds] = useState<string[]>([]);
  const [tick, setTick] = useState(() => Date.now());
  const [statsByCamera, setStatsByCamera] = useState<Map<string, DetectionStats>>(new Map());
  const [frameLabel, setFrameLabel] = useState("프레임 -");
  const [boxLabel, setBoxLabel] = useState("박스 0");
  const [overlaySnap, setOverlaySnap] = useState<OverlayState | null>(null);
  const [listOpen, setListOpen] = useState(false);

  const { selectedId, applyFrame } = live;
  useEffect(() => {
    let stopped = false;
    getLatest(selectedId)
      .then((frame) => {
        if (!stopped && frame) applyFrame(frame, false);
      })
      .catch(() => undefined);
    return () => {
      stopped = true;
    };
  }, [selectedId, applyFrame]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const overlay = live.overlayRef.current;
      if (overlay.cameraId !== live.selectedId || overlay.frame < 0) {
        setFrameLabel("프레임 -");
        setBoxLabel("박스 0");
        return;
      }
      setFrameLabel(`프레임 ${overlay.frame}`);
      setBoxLabel(`박스 ${overlay.boxes.length}`);
      setOverlaySnap({ ...overlay, boxes: overlay.boxes.slice() });
    }, 200);
    return () => window.clearInterval(timer);
  }, [live.overlayRef, live.selectedId]);

  const alertCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const alert of live.unconfirmedAlerts) {
      counts.set(alert.camera_id, (counts.get(alert.camera_id) ?? 0) + 1);
    }
    return counts;
  }, [live.unconfirmedAlerts]);

  // 탭이 보일 때만 30초마다 기간 끝을 다시 잡아 카드 집계가 따라가게 한다.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) setTick(Date.now());
    }, 30000);
    const onVisibility = () => {
      if (!document.hidden) setTick(Date.now());
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const searched = useMemo(() => {
    const text = query.trim().toLowerCase();
    return live.cameras.filter((camera) => {
      if (camera.lat == null || camera.lon == null) return false;
      const place = splitPlace(camera.name, camera.camera_id);
      const haystack = `${camera.camera_id} ${camera.name ?? ""} ${place.road} ${place.title}`.toLowerCase();
      if (text && !haystack.includes(text)) return false;
      const alerts = alertCounts.get(camera.camera_id) ?? 0;
      if (applied.cameraStatus === "online" && isOffline(camera)) return false;
      if (applied.cameraStatus === "alert" && alerts === 0) return false;
      if (!matchesAlertCount(alerts, applied.alertCount)) return false;
      return true;
    });
  }, [live.cameras, query, alertCounts, applied]);

  const visibleKey = visibleIds.slice().sort().join(",");
  const range = useMemo(() => periodRange(applied.period, new Date(tick)), [applied.period, tick]);
  useEffect(() => {
    const ids = visibleKey ? visibleKey.split(",") : [];
    const wanted = ids.filter((id) => searched.some((camera) => camera.camera_id === id));
    if (!wanted.length) return;
    let stopped = false;
    const queue = [...wanted];
    const found = new Map<string, DetectionStats>();
    const workers = Array.from({ length: 4 }, async () => {
      while (queue.length && !stopped) {
        const cameraId = queue.shift();
        if (!cameraId) return;
        const key = `${cameraId}|${range.from}|${range.to}`;
        const cached = statsCache.get(key);
        if (cached && Date.now() - cached.at < 25000) {
          found.set(cameraId, cached.stats);
          continue;
        }
        const params = new URLSearchParams({ camera_id: cameraId, from: range.from, to: range.to });
        try {
          const stats = await getDetectionStats(params);
          statsCache.set(key, { at: Date.now(), stats });
          found.set(cameraId, stats);
        } catch {
          /* 한 대 실패가 지도 전체를 막지 않는다. */
        }
      }
    });
    void Promise.all(workers).then(() => {
      if (stopped) return;
      setStatsByCamera((current) => {
        const next = new Map(current);
        for (const [id, stats] of found) next.set(id, stats);
        return next;
      });
    });
    return () => {
      stopped = true;
    };
  }, [visibleKey, range.from, range.to, searched]);

  const displayCameras = useMemo(() => {
    if (!applied.classes.length) return searched;
    return searched.filter((camera) => {
      const stats = statsByCamera.get(camera.camera_id);
      if (!stats) return true;
      return summarize(stats, applied.classes).total > 0;
    });
  }, [searched, statsByCamera, applied.classes]);

  const cards = useMemo(() => {
    const inView = new Set(visibleIds);
    const rows = displayCameras.filter((camera) => inView.has(camera.camera_id));
    const decorated = rows.map((camera) => {
      const totals = summarize(statsByCamera.get(camera.camera_id), applied.classes);
      return { camera, totals, alerts: alertCounts.get(camera.camera_id) ?? 0 };
    });
    const filtered = applied.classes.length
      ? decorated.filter((row) => !statsByCamera.has(row.camera.camera_id) || row.totals.total > 0)
      : decorated;
    filtered.sort((a, b) => {
      if (sortKey === "alerts") return b.alerts - a.alerts || a.camera.camera_id.localeCompare(b.camera.camera_id);
      return b.totals.latestHour.localeCompare(a.totals.latestHour) || b.totals.total - a.totals.total;
    });
    return filtered;
  }, [displayCameras, visibleIds, statsByCamera, applied.classes, alertCounts, sortKey]);

  const totals = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of cards) map.set(row.camera.camera_id, row.totals.total);
    return map;
  }, [cards]);

  const alertIds = useMemo(() => new Set(alertCounts.keys()), [alertCounts]);
  const selectedCamera = live.cameras.find((camera) => camera.camera_id === live.selectedId) ?? null;
  const twinObjects = useMemo(() => {
    if (!selectedCamera) return [];
    const rows = objectsForCamera(selectedCamera, overlaySnap);
    if (!applied.classes.length) return rows;
    return rows.filter((object) => applied.classes.includes(object.className));
  }, [selectedCamera, overlaySnap, applied.classes]);
  const visibleObjects = useMemo(
    () => twinObjects.filter((object) => passesRisk(object.riskScore, applied.riskLevels)),
    [twinObjects, applied.riskLevels],
  );
  const peakRisk = twinObjects.reduce((best, object) => Math.max(best, object.riskScore), 0);
  const objectDemo = twinObjects.some((object) => object.isDemo);
  const events = useMemo(
    () =>
      riskEvents(live.unconfirmedAlerts).filter((event) => passesRisk(event.riskScore, applied.riskLevels)),
    [live.unconfirmedAlerts, applied.riskLevels],
  );

  function openCamera(cameraId: string) {
    if (cameraId !== live.selectedId) live.selectCamera(cameraId);
    setExpandedId(cameraId);
    window.setTimeout(() => {
      document.getElementById(`camera-card-${cameraId}`)?.scrollIntoView({ inline: "center", block: "nearest" });
    }, 40);
  }

  const missingCoords = live.cameras.length > 0 && live.cameras.every((camera) => camera.lat == null || camera.lon == null);

  return (
    <div className="monitor">
      <FilterSidebar
        open={sidebarOpen}
        draft={draft}
        onChange={setDraft}
        onToggle={() => setSidebarOpen((value) => !value)}
        onReset={() => {
          setDraft(DEFAULT_FILTERS);
          setApplied(DEFAULT_FILTERS);
        }}
        onApply={() => setApplied(draft)}
      />
      <div className="monitor-main">
        <div className="kpi-grid">
          <article className="kpi">
            <small>연결 카메라</small>
            <strong>{live.cameras.length}</strong>
          </article>
          <article className="kpi">
            <small>실시간 추적 객체</small>
            <strong>{twinObjects.length ? twinObjects.length : objectDemo ? 0 : "데이터 없음"}</strong>
          </article>
          <article className="kpi">
            <small>미확인 경고</small>
            <strong>{live.unconfirmedAlerts.length}</strong>
          </article>
          <article className="kpi">
            <small>최고 위험도</small>
            <strong style={twinObjects.length ? { color: RISK_THEME[riskLevel(peakRisk)].fill } : undefined}>
              {twinObjects.length ? peakRisk : "데이터 없음"}
            </strong>
          </article>
        </div>
        {objectDemo ? <p className="demo-badge">예시 데이터</p> : null}
        <div className="twin-split">
          <section className="panel-card map-card">
            <header className="panel-head">
              <div>
                <strong>2D 디지털 트윈 · 지도</strong>
                <small>검출 객체를 실제 좌표에 표시</small>
              </div>
              <div className="chip-row">
                <span className="chip">{applied.layers.heat ? "히트맵 켜짐" : "히트맵 꺼짐"}</span>
                <span className="chip">객체 {visibleObjects.length}</span>
              </div>
            </header>
            <div className="map-frame">
              <div className="map-tools">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="카메라·교차로 이름"
                  aria-label="카메라 검색"
                />
                <select value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)} aria-label="정렬">
                  <option value="alerts">경고 많은 순</option>
                  <option value="recent">최근 검출 순</option>
                </select>
              </div>
              {live.camerasError ? <p className="map-error">{live.camerasError}</p> : null}
              {missingCoords ? <p className="map-error">위경도가 있는 카메라가 없습니다.</p> : null}
              <CameraMap
                cameras={displayCameras}
                alertIds={alertIds}
                totals={totals}
                selectedId={expandedId ?? live.selectedId}
                period={applied.period}
                layoutToken={Number(sidebarOpen) + Number(listOpen)}
                objects={applied.layers.objects || applied.layers.heat ? visibleObjects : []}
                showCameras={applied.layers.cameras}
                showObjects={applied.layers.objects}
                showHeat={applied.layers.heat}
                riskLevels={applied.riskLevels}
                onSelect={openCamera}
                onBounds={setVisibleIds}
              />
              <div className="map-legend">
                <span><i className="obj-mark shape-circle" /> 차량</span>
                <span><i className="obj-mark shape-square" style={{ background: RISK_THEME.high.fill }} /> 보행자(위험)</span>
                <span><i className="obj-mark shape-diamond" style={{ background: RISK_THEME.mid.fill }} /> 포트홀·낙하물</span>
                <span><i className="heat-swatch" /> 위험도 히트맵</span>
              </div>
            </div>
          </section>
          <CameraPanel camera={selectedCamera} objects={visibleObjects} frameLabel={frameLabel} boxLabel={boxLabel} />
        </div>
        <RiskEventTable events={events} />
        <section className="panel-card">
          <button type="button" className="fold" onClick={() => setListOpen((value) => !value)} aria-expanded={listOpen}>
            카메라 목록 {listOpen ? "접기" : "펼치기"}
          </button>
          {listOpen ? (
            <div className="card-rail">
              {cards.length ? (
                cards.map(({ camera, totals: count, alerts }) => (
                  <CameraCard
                    key={camera.camera_id}
                    camera={camera}
                    vehicle={count.vehicle}
                    person={count.person}
                    defect={count.defect}
                    alerts={alerts}
                    expanded={expandedId === camera.camera_id}
                    onOpen={() => openCamera(camera.camera_id)}
                    frameLabel={frameLabel}
                    boxLabel={boxLabel}
                  />
                ))
              ) : (
                <p className="empty rail-empty">이 지도 영역에 표시할 카메라가 없습니다.</p>
              )}
            </div>
          ) : null}
        </section>
      </div>
      <LatencyPanel />
    </div>
  );
}

function CameraCard({
  camera,
  vehicle,
  person,
  defect,
  alerts,
  expanded,
  onOpen,
  frameLabel,
  boxLabel,
}: {
  camera: Camera;
  vehicle: number;
  person: number;
  defect: number;
  alerts: number;
  expanded: boolean;
  onOpen: () => void;
  frameLabel: string;
  boxLabel: string;
}) {
  const place = splitPlace(camera.name, camera.camera_id);
  const offline = isOffline(camera);
  const badge = alerts > 0 ? "경고" : offline ? "오프라인" : "정상";
  return (
    <article id={`camera-card-${camera.camera_id}`} className={expanded ? "cam-card open" : "cam-card"}>
      <button type="button" className="card-face" onClick={onOpen}>
        <span className={alerts > 0 ? "badge alert" : offline ? "badge off" : "badge ok"}>{badge}</span>
        <strong>{place.title}</strong>
        <small>{place.road}</small>
        <span className="counts">
          <span title="차량">
            <i className="ico car" />
            {vehicle}
          </span>
          <span title="보행자">
            <i className="ico person" />
            {person}
          </span>
          <span title="결함">
            <i className="ico defect" />
            {defect}
          </span>
        </span>
      </button>
      {expanded ? (
        <div className="meta">
          <span>{camera.camera_id}</span>
          <span>{frameLabel}</span>
          <span>{boxLabel}</span>
        </div>
      ) : null}
    </article>
  );
}
