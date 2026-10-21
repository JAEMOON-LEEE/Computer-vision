import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import L from "leaflet";
import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip as MapTooltip, useMap } from "react-leaflet";
import { getDetectionStats } from "../api";
import { MAP_TILES } from "../components/CameraMap";
import { useLive } from "../live";
import { periodRange } from "../mapModel";
import { RISK_THEME, alertTypeLabel, riskLevel } from "../risk";
import { heatPoints, hourlyDetections, hourlyRisk, repeatedSegments, riskByType } from "../twinModel";
import type { Camera } from "../types";

type AnalysisPeriod = "today" | "7d" | "30d";

function rangeFor(period: AnalysisPeriod): { from: string; to: string } {
  if (period === "30d") {
    const now = new Date();
    const to = periodRange("today", now).to;
    const fromDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    const from = periodRange("today", fromDate).from;
    return { from, to };
  }
  return periodRange(period);
}

function downloadCsv(filename: string, rows: string[][]) {
  const body = rows
    .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([`\uFEFF${body}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function FitCameras({ cameras }: { cameras: Camera[] }) {
  const map = useMap();
  useEffect(() => {
    const points = cameras.filter((camera) => camera.lat != null && camera.lon != null);
    if (!points.length) return;
    const bounds = L.latLngBounds(points.map((camera) => [camera.lat as number, camera.lon as number]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
  }, [cameras, map]);
  return null;
}

export function AnalysisPage() {
  const { cameras } = useLive();
  const [period, setPeriod] = useState<AnalysisPeriod>("today");
  const [byHour, setByHour] = useState<{ hour: string; count: number }[] | null>(null);

  useEffect(() => {
    const range = rangeFor(period);
    const params = new URLSearchParams({ from: range.from, to: range.to });
    let stopped = false;
    getDetectionStats(params)
      .then((stats) => {
        if (!stopped) setByHour(stats.by_hour);
      })
      .catch(() => {
        if (!stopped) setByHour([]);
      });
    return () => {
      stopped = true;
    };
  }, [period]);

  const segments = useMemo(() => repeatedSegments(cameras), [cameras]);
  const heat = useMemo(() => heatPoints(cameras, segments), [cameras, segments]);
  const hours = useMemo(() => hourlyRisk(), []);
  const detections = useMemo(() => hourlyDetections(byHour), [byHour]);
  const types = useMemo(() => riskByType(), []);
  const typeRows = useMemo(
    () => types.rows.map((row) => ({ ...row, type: alertTypeLabel(row.type) })),
    [types],
  );
  const demo = segments.some((item) => item.isDemo) || hours.isDemo || types.isDemo || heat.some((item) => item.isDemo);
  const eventTotal = hours.isDemo ? hours.rows.reduce((sum, row) => sum + row.count, 0) : null;
  const avgRisk = types.rows.length
    ? Math.round(types.rows.reduce((sum, row) => sum + row.count, 0) / types.rows.length)
    : null;
  const hourMax = Math.max(1, ...hours.rows.map((row) => row.count));
  const detectionMax = Math.max(1, ...detections.map((row) => row.count));
  const typeMax = Math.max(1, ...types.rows.map((row) => row.count));
  const segmentMax = Math.max(1, ...segments.map((item) => item.count));

  function exportCsv() {
    const rows = [
      ["구분", "이름", "값"],
      ...segments.map((item) => ["반복 구간", `${item.rank}. ${item.name} (${item.detail})`, String(item.count)]),
      ...(hours.isDemo
        ? hours.rows.map((row) => ["위험 이벤트 시간대", `${String(row.hour).padStart(2, "0")}시`, String(row.count)])
        : []),
      ...detections.map((row) => ["검출 수", `${String(row.hour).padStart(2, "0")}시`, String(row.count)]),
    ];
    downloadCsv("twinsight-analysis.csv", rows);
  }

  return (
    <section className="analysis">
      <header className="analysis-bar">
        <div className="segment light">
          {(
            [
              ["today", "오늘"],
              ["7d", "최근 7일"],
              ["30d", "최근 30일"],
            ] as const
          ).map(([value, label]) => (
            <button key={value} type="button" className={period === value ? "on" : ""} onClick={() => setPeriod(value)}>
              {label}
            </button>
          ))}
        </div>
        <button type="button" className="ghost-dark" onClick={exportCsv}>
          CSV 내보내기
        </button>
      </header>
      {demo ? <p className="demo-badge">예시 데이터</p> : null}
      <div className="kpi-grid">
        <Kpi label="위험 이벤트" value={eventTotal == null ? "데이터 없음" : String(eventTotal)} />
        <Kpi label="평균 위험도" value={avgRisk == null ? "데이터 없음" : String(avgRisk)} />
        <Kpi label="반복 위험 구간" value={segments.length ? String(segments.length) : "데이터 없음"} />
        <Kpi label="확인 처리율" value={demo ? "68%" : "데이터 없음"} />
      </div>
      <div className="twin-split analysis-split">
        <article className="panel-card map-card">
          <header className="panel-head">
            <strong>위험도 히트맵</strong>
          </header>
          <div className="map-frame">
            {heat.length || cameras.some((camera) => camera.lat != null) ? (
              <MapContainer center={[37.5, 127.0]} zoom={11} zoomControl={false} className="leaflet-map">
                <TileLayer attribution={MAP_TILES.attribution} url={MAP_TILES.url} maxZoom={19} />
                <FitCameras cameras={cameras} />
                {heat.map((point, index) => (
                  <Circle
                    key={`heat-${index}`}
                    center={[point.lat, point.lon]}
                    radius={80 + point.weight * 220}
                    pathOptions={{
                      color: RISK_THEME.high.fill,
                      fillColor: point.weight > 0.66 ? RISK_THEME.high.fill : point.weight > 0.4 ? RISK_THEME.mid.fill : RISK_THEME.low.fill,
                      fillOpacity: 0.08 + point.weight * 0.28,
                      weight: 0,
                    }}
                  />
                ))}
                {segments.map((segment) => (
                  <CircleMarker key={segment.rank} center={[segment.lat, segment.lon]} radius={14} pathOptions={{ color: "#fff", weight: 2, fillColor: RISK_THEME.high.fill, fillOpacity: 1 }}>
                    <MapTooltip permanent direction="center" className="rank-tip">
                      {segment.rank}
                    </MapTooltip>
                  </CircleMarker>
                ))}
              </MapContainer>
            ) : (
              <p className="empty map-empty">데이터 없음</p>
            )}
            <div className="map-legend">
              <span>발생 밀도</span>
              <i className="obj-mark shape-circle" style={{ background: RISK_THEME.low.fill, opacity: 0.45 }} />
              <i className="obj-mark shape-circle" style={{ background: RISK_THEME.mid.fill, opacity: 0.65 }} />
              <i className="obj-mark shape-circle" style={{ background: RISK_THEME.high.fill, opacity: 0.85 }} />
              <span>낮음에서 높음</span>
            </div>
          </div>
        </article>
        <article className="panel-card">
          <header className="panel-head">
            <strong>반복 위험 구간 Top 5</strong>
          </header>
          {segments.length ? (
            <ol className="segment-list">
              {segments.map((segment) => (
                <li key={segment.rank}>
                  <b className="rank">{segment.rank}</b>
                  <div>
                    <strong>{segment.name}</strong>
                    <small>{segment.detail}</small>
                    <i className="meter">
                      <i
                        style={{
                          width: `${(segment.count / segmentMax) * 100}%`,
                          background: RISK_THEME[segment.rank === 1 ? "high" : segment.rank <= 3 ? "mid" : "low"].fill,
                        }}
                      />
                    </i>
                  </div>
                  <em>
                    {segment.count}
                    <small>건</small>
                  </em>
                </li>
              ))}
            </ol>
          ) : (
            <p className="empty">데이터 없음</p>
          )}
        </article>
      </div>
      <div className="twin-split analysis-split">
        <article className="panel-card">
          <header className="panel-head">
            <strong>시간대별 위험 이벤트</strong>
          </header>
          {hours.rows.some((row) => row.count > 0) ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={hours.rows}>
                <CartesianGrid stroke="#E1E4EA" vertical={false} />
                <XAxis dataKey="hour" ticks={[0, 6, 12, 18]} tickFormatter={(value) => String(value).padStart(2, "0")} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="건수">
                  {hours.rows.map((row) => {
                    const ratio = row.count / hourMax;
                    const level = riskLevel(ratio * 100);
                    return <Cell key={row.hour} fill={RISK_THEME[level].fill} />;
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="empty">데이터 없음</p>
          )}
        </article>
        <article className="panel-card">
          <header className="panel-head">
            <strong>유형별 위험 이벤트</strong>
          </header>
          {typeRows.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={typeRows} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid stroke="#E1E4EA" horizontal={false} />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="type" width={148} />
                <Tooltip />
                <Bar dataKey="count" name="건수">
                  {typeRows.map((row) => (
                    <Cell key={row.type} fill={RISK_THEME[riskLevel((row.count / typeMax) * 100)].fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="empty">데이터 없음</p>
          )}
        </article>
      </div>
      <article className="panel-card">
        <header className="panel-head">
          <strong>시간대별 검출 수 (전체 클래스)</strong>
        </header>
        {detections.some((row) => row.count > 0) ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={detections}>
              <CartesianGrid stroke="#E1E4EA" vertical={false} />
              <XAxis dataKey="hour" ticks={[0, 6, 12, 18]} tickFormatter={(value) => String(value).padStart(2, "0")} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" name="검출 수" fill="#1E2A47">
                {detections.map((row) => (
                  <Cell key={row.hour} fill="#1E2A47" opacity={0.45 + (row.count / detectionMax) * 0.55} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="empty">데이터 없음</p>
        )}
      </article>
    </section>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <article className="kpi">
      <small>{label}</small>
      <strong>{value}</strong>
    </article>
  );
}
