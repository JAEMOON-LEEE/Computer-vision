import { useEffect, useState } from "react";
import { formatKst } from "../format";
import { alertTypeLabel } from "../risk";
import { useLive } from "../live";
import type { AlertItem, Camera } from "../types";

type Props = {
  open: boolean;
  onClose: () => void;
};

type Tab = "all" | "camera";

function cameraLabel(cameras: Camera[], cameraId: string): string {
  const name = cameras.find((camera) => camera.camera_id === cameraId)?.name;
  return name || cameraId;
}

export function AlertDrawer({ open, onClose }: Props) {
  const { alerts, unconfirmedAlerts, cameras, alertError, confirmAlert, dismissAlert, selectedId } = useLive();
  const [tab, setTab] = useState<Tab>("all");

  useEffect(() => {
    if (open) setTab("all");
  }, [open]);

  if (!open) return null;
  const rows = tab === "all" ? unconfirmedAlerts : alerts.slice(0, 40);
  const empty = tab === "all" ? "미확인 경고가 없습니다." : "이 카메라의 경고가 없습니다.";
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <h2>경고</h2>
          <button type="button" onClick={onClose} aria-label="경고 닫기">
            닫기
          </button>
        </div>
        <div className="drawer-tabs" role="tablist">
          <button type="button" className={tab === "all" ? "on" : ""} onClick={() => setTab("all")}>
            전체 미확인
          </button>
          <button type="button" className={tab === "camera" ? "on" : ""} onClick={() => setTab("camera")}>
            선택 카메라
          </button>
        </div>
        {tab === "camera" ? <p className="drawer-camera">{selectedId}</p> : null}
        {alertError ? <p className="err">{alertError}</p> : null}
        <ul>
          {rows.length ? (
            rows.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                cameraName={cameraLabel(cameras, alert.camera_id)}
                onConfirm={() => void confirmAlert(alert.id)}
                onDismiss={() => void dismissAlert(alert.id)}
              />
            ))
          ) : (
            <li className="empty">{empty}</li>
          )}
        </ul>
      </aside>
    </div>
  );
}

function AlertRow({
  alert,
  cameraName,
  onConfirm,
  onDismiss,
}: {
  alert: AlertItem;
  cameraName: string;
  onConfirm: () => void;
  onDismiss: () => void;
}) {
  return (
    <li className="alert">
      <strong>
        {alertTypeLabel(alert.type)} · {alert.status}
      </strong>
      <small>{cameraName}</small>
      <small>{alert.message}</small>
      <small>
        #{alert.id} {alert.alert_id} / frame {alert.frame}
      </small>
      <small>접수 {formatKst(alert.created_at)} KST</small>
      <div className="alert-actions">
        <button type="button" className="confirm" onClick={onConfirm}>
          확인
        </button>
        <button type="button" className="dismiss" onClick={onDismiss}>
          기각
        </button>
      </div>
    </li>
  );
}
