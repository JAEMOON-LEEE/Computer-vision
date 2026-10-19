import { formatKst } from "../format";
import { useLive } from "../live";

type Props = {
  open: boolean;
  onClose: () => void;
};

export function AlertDrawer({ open, onClose }: Props) {
  const { alerts, alertError, confirmAlert, dismissAlert, selectedId } = useLive();
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <h2>경고</h2>
          <button type="button" onClick={onClose} aria-label="경고 닫기">
            닫기
          </button>
        </div>
        <p className="drawer-camera">{selectedId}</p>
        {alertError ? <p className="err">{alertError}</p> : null}
        <ul>
          {alerts.length ? (
            alerts.slice(0, 40).map((alert) => (
              <li key={alert.id} className="alert">
                <strong>
                  {alert.type} · {alert.status}
                </strong>
                <small>{alert.message}</small>
                <small>
                  #{alert.id} {alert.alert_id} / frame {alert.frame}
                </small>
                <small>접수 {formatKst(alert.created_at)} KST</small>
                <div className="alert-actions">
                  <button type="button" className="confirm" onClick={() => void confirmAlert(alert.id)}>
                    확인
                  </button>
                  <button type="button" className="dismiss" onClick={() => void dismissAlert(alert.id)}>
                    기각
                  </button>
                </div>
              </li>
            ))
          ) : (
            <li className="empty">이 카메라의 경고가 없습니다.</li>
          )}
        </ul>
      </aside>
    </div>
  );
}
