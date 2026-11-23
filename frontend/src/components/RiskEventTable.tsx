import { Link } from "react-router-dom";
import { formatKstTime } from "../format";
import { useLive } from "../live";
import { splitPlace } from "../mapModel";
import { RISK_THEME, alertTypeLabel, riskLevel } from "../risk";
import type { RiskEvent } from "../twinModel";

type Props = {
  events: RiskEvent[];
};

export function RiskEventTable({ events }: Props) {
  const { cameras, confirmAlert, dismissAlert } = useLive();
  const demo = events.some((event) => event.isDemo);
  return (
    <section className="panel-card">
      <header className="panel-head">
        <div>
          <strong>위험 이벤트</strong>
          {demo ? <p className="demo-badge">예시 데이터</p> : null}
          {demo ? <small>위험도는 심각도에서 임시 환산한 값입니다.</small> : null}
        </div>
        <Link to="/history">이력에서 전체 보기</Link>
      </header>
      <div className="table-wrap plain">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>카메라</th>
              <th>유형</th>
              <th>위험도</th>
              <th>상태</th>
              <th>처리</th>
            </tr>
          </thead>
          <tbody>
            {events.length ? (
              events.map((event) => {
                const camera = cameras.find((item) => item.camera_id === event.cameraId);
                const place = splitPlace(camera?.name ?? null, event.cameraId);
                const theme = RISK_THEME[riskLevel(event.riskScore)];
                return (
                  <tr key={event.id}>
                    <td>{formatKstTime(event.timeMs)}</td>
                    <td>{place.title}</td>
                    <td>{alertTypeLabel(event.type)}</td>
                    <td>
                      <b className="risk-badge" style={{ background: theme.badgeBg, color: theme.badgeText }}>
                        {theme.label} {event.riskScore}
                      </b>
                    </td>
                    <td>{event.status}</td>
                    <td className="row-actions">
                      <button type="button" className="confirm" onClick={() => void confirmAlert(event.id)}>
                        확인
                      </button>
                      <button type="button" className="dismiss" onClick={() => void dismissAlert(event.id)}>
                        기각
                      </button>
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={6}>데이터 없음</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
