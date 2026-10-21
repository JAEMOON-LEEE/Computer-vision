import { RISK_THEME, type RiskLevel } from "../risk";
import { CLASSES } from "../types";
import type { Filters } from "../mapModel";

type Props = {
  open: boolean;
  draft: Filters;
  onChange: (next: Filters) => void;
  onToggle: () => void;
  onReset: () => void;
  onApply: () => void;
};

export function FilterSidebar({ open, draft, onChange, onToggle, onReset, onApply }: Props) {
  return (
    <aside className={open ? "filter-side" : "filter-side collapsed"}>
      <div className="filter-head">
        <strong>필터</strong>
        <button type="button" className="collapse" onClick={onToggle} aria-label={open ? "필터 접기" : "필터 펼치기"}>
          {open ? "«" : "»"}
        </button>
      </div>
      {open ? (
        <>
          <div className="filter-body">
            <section>
              <h2>검출 클래스</h2>
              <div className="class-grid">
                {CLASSES.map((name) => {
                  const active = draft.classes.includes(name);
                  return (
                    <button
                      key={name}
                      type="button"
                      className={active ? "class-card on" : "class-card"}
                      onClick={() =>
                        onChange({
                          ...draft,
                          classes: active ? draft.classes.filter((item) => item !== name) : [...draft.classes, name],
                        })
                      }
                    >
                      <ClassGlyph name={name} />
                      <span>{name}</span>
                    </button>
                  );
                })}
              </div>
            </section>
            <section>
              <h2>미확인 경고 수</h2>
              {(
                [
                  [0, "0건"],
                  [1, "1건 이상"],
                  [3, "3건 이상"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="choice">
                  <input
                    type="radio"
                    name="alert-count"
                    checked={draft.alertCount === value}
                    onChange={() => onChange({ ...draft, alertCount: value })}
                  />
                  {label}
                </label>
              ))}
            </section>
            <section>
              <h2>지도 레이어</h2>
              {(
                [
                  ["cameras", "카메라"],
                  ["objects", "검출 객체 위치"],
                  ["heat", "위험도 히트맵"],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="choice">
                  <input
                    type="checkbox"
                    checked={draft.layers[key]}
                    onChange={() => onChange({ ...draft, layers: { ...draft.layers, [key]: !draft.layers[key] } })}
                  />
                  {label}
                </label>
              ))}
              <label className="choice muted-choice">
                <input type="checkbox" checked={false} disabled />
                이동 경로
                <small>준비 중</small>
              </label>
            </section>
            <section>
              <h2>위험도</h2>
              {(["high", "mid", "low"] as RiskLevel[]).map((level) => (
                <label key={level} className="choice">
                  <input
                    type="checkbox"
                    checked={draft.riskLevels[level]}
                    onChange={() =>
                      onChange({ ...draft, riskLevels: { ...draft.riskLevels, [level]: !draft.riskLevels[level] } })
                    }
                  />
                  <i className="risk-dot" style={{ background: RISK_THEME[level].fill }} />
                  {RISK_THEME[level].label} ({RISK_THEME[level].rule})
                </label>
              ))}
            </section>
            <section>
              <h2>기간</h2>
              <div className="segment">
                {(
                  [
                    ["live", "실시간"],
                    ["1h", "1시간"],
                    ["today", "오늘"],
                    ["7d", "7일"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    className={draft.period === value ? "on" : ""}
                    onClick={() => onChange({ ...draft, period: value })}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </section>
            <section>
              <h2>카메라 상태</h2>
              {(
                [
                  ["all", "전체"],
                  ["online", "온라인"],
                  ["alert", "경고 있음"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="choice">
                  <input
                    type="radio"
                    name="camera-status"
                    checked={draft.cameraStatus === value}
                    onChange={() => onChange({ ...draft, cameraStatus: value })}
                  />
                  {label}
                </label>
              ))}
            </section>
          </div>
          <div className="filter-actions">
            <button type="button" className="ghost" onClick={onReset}>
              초기화
            </button>
            <button type="button" className="apply" onClick={onApply}>
              적용
            </button>
          </div>
        </>
      ) : null}
    </aside>
  );
}

function ClassGlyph({ name }: { name: string }) {
  if (name === "person") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="5" r="2.2" />
        <path d="M12 9v6M8 21l4-6 4 6M7 12h10" />
      </svg>
    );
  }
  if (name === "pothole" || name === "crack" || name === "debris") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 16l4-8h8l4 8" />
        <path d="M8 16l2-4h4l2 4" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 14h16v4H4zM6 14l2-4h8l2 4" />
      <circle cx="7" cy="18" r="1.4" />
      <circle cx="17" cy="18" r="1.4" />
    </svg>
  );
}
