import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { MapContainer, Marker, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from "react-leaflet";
import type { Camera } from "../types";
import { periodLabel, splitPlace, type Period } from "../mapModel";
import "leaflet/dist/leaflet.css";

// CARTO 베이스맵은 키가 필요하다. 키는 저장소 루트 .env의 VITE_CARTO_KEY.
// 키가 없으면 OpenStreetMap 기본 지도를 써서 팀원 PC에서도 지도가 뜨게 한다.
const CARTO_KEY = (import.meta.env.VITE_CARTO_KEY ?? "").trim();
const TILES = CARTO_KEY
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
  onSelect: (cameraId: string) => void;
  onBounds: (ids: string[]) => void;
};

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

export function CameraMap({ cameras, alertIds, totals, selectedId, period, layoutToken, onSelect, onBounds }: Props) {
  const located = useMemo(
    () => cameras.filter((camera) => camera.lat != null && camera.lon != null),
    [cameras],
  );
  const label = periodLabel(period);
  return (
    <MapContainer center={[37.5, 127.0]} zoom={11} zoomControl={false} className="leaflet-map">
      <TileLayer attribution={TILES.attribution} url={TILES.url} maxZoom={19} />
      <ZoomControl position="topright" />
      <FitOnce cameras={located} />
      <Invalidate token={layoutToken} />
      <BoundsReporter cameras={located} onBounds={onBounds} />
      {located.map((camera) => {
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
            {selected ? (
              <Tooltip permanent direction="top" offset={[0, -12]} className="camera-chip">
                <strong>{place.title}</strong>
                <span>
                  {label} 검출 {totals.get(camera.camera_id) ?? 0}건
                </span>
              </Tooltip>
            ) : null}
          </Marker>
        );
      })}
    </MapContainer>
  );
}
