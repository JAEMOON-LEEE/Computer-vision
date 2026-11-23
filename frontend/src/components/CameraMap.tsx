import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { Circle, MapContainer, Marker, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import type { RiskLevelFilter } from "../mapModel";
import { periodLabel, splitPlace, type Period } from "../mapModel";
import { RISK_THEME, riskLevel } from "../risk";
import { classLabel, markerShape, passesRisk, type TwinObject } from "../twinModel";
import type { Camera } from "../types";
import "leaflet/dist/leaflet.css";

// CARTO 베이스맵은 키가 필요하다. 키는 저장소 루트 .env의 VITE_CARTO_KEY.
// 키가 없으면 OpenStreetMap 기본 지도를 써서 팀원 PC에서도 지도가 뜨게 한다.
const CARTO_KEY = (import.meta.env.VITE_CARTO_KEY ?? "").trim();
export const MAP_TILES = CARTO_KEY
  ? {
      url: `https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png?key=${encodeURIComponent(CARTO_KEY)}`,
      attribution: '&copy; OpenStreetMap contributors, &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }
  : {
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    };
if (!CARTO_KEY) {
  console.info("VITE_CARTO_KEY가 없어 OpenStreetMap 기본 지도를 씁니다.");
}

type Props = {
  cameras: Camera[];
  alertIds: Set<string>;
  totals: Map<string, number>;
  selectedId: string | null;
  period: Period;
  layoutToken: number;
  objects: TwinObject[];
  showCameras: boolean;
  showObjects: boolean;
  showHeat: boolean;
  riskLevels: RiskLevelFilter;
  onSelect: (cameraId: string) => void;
  onBounds: (ids: string[]) => void;
};

function objectIcon(object: TwinObject) {
  const shape = markerShape(object.className);
  const color = RISK_THEME[riskLevel(object.riskScore)].fill;
  return L.divIcon({
    className: "marker-wrap",
    html: `<span class="obj-mark shape-${shape}" style="background:${color}"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

function markerIcon(alert: boolean, selected: boolean) {
  const size = selected ? 22 : 16;
  return L.divIcon({
    className: "marker-wrap",
    html: `<span class="marker-dot${alert ? " is-alert" : ""}${selected ? " is-selected" : ""}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function BoundsReporter({ cameras, onBounds }: { cameras: Camera[]; onBounds: (ids: string[]) => void }) {
  const map = useMapEvents({
    moveend: () => report(),
    zoomend: () => report(),
  });
  function report() {
    const bounds = map.getBounds();
    onBounds(
      cameras
        .filter((camera) => camera.lat != null && camera.lon != null && bounds.contains([camera.lat, camera.lon]))
        .map((camera) => camera.camera_id),
    );
  }
  useEffect(() => {
    report();
    // 카메라 목록이 바뀌면 현재 화면 안 대상을 다시 고른다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras, map]);
  return null;
}

function FitOnce({ cameras }: { cameras: Camera[] }) {
  const map = useMap();
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current) return;
    const points = cameras.filter((camera) => camera.lat != null && camera.lon != null);
    if (!points.length) return;
    fitted.current = true;
    const bounds = L.latLngBounds(points.map((camera) => [camera.lat as number, camera.lon as number]));
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 14 });
  }, [cameras, map]);
  return null;
}

function Invalidate({ token }: { token: number }) {
  const map = useMap();
  useEffect(() => {
    const timer = window.setTimeout(() => map.invalidateSize(), 220);
    return () => window.clearTimeout(timer);
  }, [token, map]);
  return null;
}

export function CameraMap({
  cameras,
  alertIds,
  totals,
  selectedId,
  period,
  layoutToken,
  objects,
  showCameras,
  showObjects,
  showHeat,
  riskLevels,
  onSelect,
  onBounds,
}: Props) {
  const located = useMemo(
    () => cameras.filter((camera) => camera.lat != null && camera.lon != null),
    [cameras],
  );
  const visibleObjects = useMemo(
    () => objects.filter((object) => passesRisk(object.riskScore, riskLevels)),
    [objects, riskLevels],
  );
  const label = periodLabel(period);
  const peak = visibleObjects.reduce((best, object) => Math.max(best, object.riskScore), 0);
  return (
    <MapContainer center={[37.5, 127.0]} zoom={11} zoomControl={false} className="leaflet-map">
      <TileLayer attribution={MAP_TILES.attribution} url={MAP_TILES.url} maxZoom={19} />
      <ZoomControl position="topright" />
      <FitOnce cameras={located} />
      <Invalidate token={layoutToken} />
      <BoundsReporter cameras={located} onBounds={onBounds} />
      {showHeat
        ? visibleObjects.map((object, index) => (
            <Circle
              key={`heat-${object.trackId ?? "x"}-${index}`}
              center={[object.lat, object.lon]}
              radius={18 + (object.riskScore / 100) * 36}
              pathOptions={{
                color: RISK_THEME[riskLevel(object.riskScore)].fill,
                fillColor: RISK_THEME[riskLevel(object.riskScore)].fill,
                fillOpacity: 0.12 + (object.riskScore / 100) * 0.38,
                weight: 0,
              }}
            />
          ))
        : null}
      {showObjects
        ? visibleObjects.map((object, index) => (
            <Marker
              key={`obj-${object.trackId ?? "x"}-${index}`}
              position={[object.lat, object.lon]}
              icon={objectIcon(object)}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                {classLabel(object.className)} · {object.riskScore}
              </Tooltip>
            </Marker>
          ))
        : null}
      {showCameras
        ? located.map((camera) => {
        const alert = alertIds.has(camera.camera_id);
        const selected = camera.camera_id === selectedId;
        const place = splitPlace(camera.name, camera.camera_id);
        return (
          <Marker
            key={camera.camera_id}
            position={[camera.lat as number, camera.lon as number]}
            icon={markerIcon(alert, selected)}
            eventHandlers={{ click: () => onSelect(camera.camera_id) }}
          >
            {camera.camera_id === selectedId && selected ? (
              <Tooltip permanent direction="top" offset={[0, -12]} className="camera-chip">
                <strong>{place.title}</strong>
                <span>
                  {camera.camera_id} · 객체 {visibleObjects.length}
                </span>
                <span>
                  {label} 검출 {totals.get(camera.camera_id) ?? 0}건
                </span>
                {visibleObjects.length ? (
                  <b
                    className="risk-badge"
                    style={{
                      background: RISK_THEME[riskLevel(peak)].badgeBg,
                      color: RISK_THEME[riskLevel(peak)].badgeText,
                    }}
                  >
                    최고 위험도 {peak}
                  </b>
                ) : (
                  <span>데이터 없음</span>
                )}
              </Tooltip>
            ) : null}
          </Marker>
        );
      })
        : null}
    </MapContainer>
  );
}
