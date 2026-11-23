import { latencyStats, useLive } from "../live";
import { RISK_THEME, riskLevel } from "../risk";
import { classLabel, type TwinObject } from "../twinModel";
import { splitPlace } from "../mapModel";
import type { Camera } from "../types";
import { TwinView3D } from "./TwinView3D";
import { VideoStage } from "./VideoStage";

type Props = {
  camera: Camera | null;
  objects: TwinObject[];
  frameLabel: string;
  boxLabel: string;
};

export function CameraPanel({ camera, objects, frameLabel, boxLabel }: Props) {
  const live = useLive();
  const stats = latencyStats(live.latencyRef.current);
  void live.latencyTick;
  if (!camera) {
    return (
      <section className="panel-card camera-panel">
        <p className="empty">선택한 카메라가 없습니다.</p>
      </section>
    );
  }
  const place = splitPlace(camera.name, camera.camera_id);
  const ranked = [...objects].sort((a, b) => b.riskScore - a.riskScore).slice(0, 5);
  const demo = objects.some((object) => object.isDemo);
  const p95 = stats.p95 === null ? "-" : `${stats.p95.toFixed(0)} ms`;
  return (
    <section className="panel-card camera-panel">
      <header className="panel-head">
        <div>
          <strong>{place.title}</strong>
          <small>
            {camera.camera_id} · 지연 p95 {p95}
          </small>
        </div>
        <span className="live-pill">LIVE</span>
      </header>
      {demo ? <p className="demo-badge">예시 데이터</p> : null}
      <h3>CCTV 영상</h3>
      <VideoStage
        cameraId={camera.camera_id}
        overlayRef={live.overlayRef}
        latencyRef={live.latencyRef}
        onSample={live.noteLatency}
      />
      <div className="meta">
        <span>{frameLabel}</span>
        <span>{boxLabel}</span>
      </div>
      <TwinView3D cameraId={camera.camera_id} objects={objects} />
      <h3>추적 객체</h3>
      {ranked.length ? (
        <ul className="track-list">
          {ranked.map((object) => {
            const level = riskLevel(object.riskScore);
            const theme = RISK_THEME[level];
            return (
              <li key={`${object.trackId ?? "x"}-${object.className}-${object.lat.toFixed(5)}`}>
                <div>
                  <b>#{object.trackId ?? "-"}</b>
                  <span>
                    {classLabel(object.className)}
                    {object.note ? ` · ${object.note}` : ""}
                  </span>
                </div>
                <div className="risk-bar" aria-hidden="true">
                  <i style={{ width: `${Math.min(100, object.riskScore)}%`, background: theme.fill }} />
                </div>
                <b style={{ color: theme.badgeText }}>{object.riskScore}</b>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="empty">데이터 없음</p>
      )}
    </section>
  );
}
