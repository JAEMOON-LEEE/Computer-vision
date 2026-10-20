import { useEffect, useMemo, useState } from "react";
import { getDetectionStats, getLatest } from "../api";
import { CameraMap } from "../components/CameraMap";
import { FilterSidebar } from "../components/FilterSidebar";
import { LatencyPanel } from "../components/LatencyPanel";
import { VideoStage } from "../components/VideoStage";
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
import type { Camera, DetectionStats } from "../types";

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
      <div className="map-column">
        <div className="map-stage">
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
            selectedId={expandedId}
            period={applied.period}
            layoutToken={Number(sidebarOpen) + (expandedId ? 1 : 0)}
            onSelect={openCamera}
            onBounds={setVisibleIds}
          />
        </div>
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
                overlayRef={live.overlayRef}
                latencyRef={live.latencyRef}
                onSample={live.noteLatency}
              />
            ))
          ) : (
            <p className="empty rail-empty">이 지도 영역에 표시할 카메라가 없습니다.</p>
          )}
        </div>
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
  overlayRef,
  latencyRef,
  onSample,
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
  overlayRef: ReturnType<typeof useLive>["overlayRef"];
  latencyRef: ReturnType<typeof useLive>["latencyRef"];
  onSample: () => void;
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
        <div className="card-video">
          <VideoStage cameraId={camera.camera_id} overlayRef={overlayRef} latencyRef={latencyRef} onSample={onSample} />
          <div className="meta">
            <span>{camera.camera_id}</span>
            <span>{frameLabel}</span>
            <span>{boxLabel}</span>
          </div>
        </div>
      ) : null}
    </article>
  );
}
