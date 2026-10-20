import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getDetectionStats, getDetections } from "../api";
import { classColor } from "../colors";
import { formatKst, kstInputToIso } from "../format";
import { useLive } from "../live";
import { CLASSES, type DetectionHistoryItem, type DetectionStats } from "../types";

const PAGE = 100;

function filterParams(cameraId: string, classNames: string[], fromText: string, toText: string) {
  const params = new URLSearchParams();
  if (cameraId) params.set("camera_id", cameraId);
  for (const name of classNames) params.append("class_name", name);
  const fromIso = kstInputToIso(fromText);
  const toIso = kstInputToIso(toText);
  if (fromIso) params.set("from", fromIso);
  if (toIso) params.set("to", toIso);
  return params;
}

function hourLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

function eventTime(row: DetectionHistoryItem): string {
  if (row.timestamp_kind === "unix_seconds") return formatKst(row.timestamp * 1000);
  return `${row.timestamp} (${row.timestamp_kind})`;
}

export function HistoryPage() {
  const { cameras } = useLive();
  const [cameraId, setCameraId] = useState("");
  const [classNames, setClassNames] = useState<string[]>([]);
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<DetectionHistoryItem[]>([]);
  const [stats, setStats] = useState<DetectionStats>({ by_class: [], by_hour: [] });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = filterParams(cameraId, classNames, fromText, toText);
    const statsParams = new URLSearchParams(params);
    params.set("limit", String(PAGE));
    params.set("offset", String(offset));
    let stopped = false;
    setLoading(true);
    Promise.all([getDetections(params), getDetectionStats(statsParams)])
      .then(([list, nextStats]) => {
        if (stopped) return;
        setItems(list.items);
        setTotal(list.total);
        setStats(nextStats);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!stopped) setError(reason instanceof Error ? reason.message : "이력 조회 실패");
      })
      .finally(() => {
        if (!stopped) setLoading(false);
      });
    return () => {
      stopped = true;
    };
  }, [cameraId, classNames, fromText, toText, offset]);

  function toggleClass(name: string) {
    setOffset(0);
    setClassNames((current) => (current.includes(name) ? current.filter((item) => item !== name) : [...current, name]));
  }

  const byClass = stats.by_class.map((row) => ({ name: row.class_name, count: row.count, fill: classColor(row.class_name) }));
  const byHour = stats.by_hour.map((row) => ({ slot: hourLabel(row.hour), count: row.count }));
  const pageEnd = Math.min(offset + items.length, total);

  return (
    <section className="history">
      <p className="note">표는 저장된 검출이고, 차트는 같은 조건의 집계입니다. 시각은 KST입니다. 목업 박스는 실제 영상 속 물체와 맞지 않습니다.</p>
      <div className="filters">
        <label>
          카메라
          <select
            value={cameraId}
            onChange={(event) => {
              setCameraId(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">전체</option>
            {cameras.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>
                {camera.name || camera.camera_id}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>클래스</legend>
          {CLASSES.map((name) => (
            <label key={name} className="check">
              <input type="checkbox" checked={classNames.includes(name)} onChange={() => toggleClass(name)} />
              {name}
            </label>
          ))}
        </fieldset>
        <label>
          시작 (KST)
          <input
            type="datetime-local"
            value={fromText}
            onChange={(event) => {
              setFromText(event.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          끝 (KST)
          <input
            type="datetime-local"
            value={toText}
            onChange={(event) => {
              setToText(event.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      {error ? <p className="err">{error}</p> : null}
      <div className="charts">
        <article>
          <h2>클래스별 검출 수</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byClass}>
              <CartesianGrid stroke="#2a3340" vertical={false} />
              <XAxis dataKey="name" stroke="#93a0b0" />
              <YAxis stroke="#93a0b0" allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" name="검출 수">
                {byClass.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </article>
        <article>
          <h2>시간대별 검출 수</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byHour}>
              <CartesianGrid stroke="#2a3340" vertical={false} />
              <XAxis dataKey="slot" stroke="#93a0b0" />
              <YAxis stroke="#93a0b0" allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="count" name="검출 수" fill="#4cc3ff" />
            </BarChart>
          </ResponsiveContainer>
        </article>
      </div>
      <p className="meta">
        {loading ? "불러오는 중" : `전체 ${total}건 중 ${total ? offset + 1 : 0}–${pageEnd}`}
      </p>
      <div className="pager">
        <button type="button" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE))}>
          이전
        </button>
        <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset((value) => value + PAGE)}>
          다음
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각 (KST)</th>
              <th>카메라</th>
              <th>클래스</th>
              <th>신뢰도</th>
              <th>트랙</th>
              <th>프레임</th>
              <th>실행</th>
            </tr>
          </thead>
          <tbody>
            {items.length ? (
              items.map((row, index) => (
                <tr key={`${row.run_id}-${row.frame}-${row.class_name}-${row.track_id ?? "x"}-${index}`}>
                  <td>{eventTime(row)}</td>
                  <td>{row.camera_id}</td>
                  <td>{row.class_name}</td>
                  <td>{row.confidence.toFixed(2)}</td>
                  <td>{row.track_id ?? "-"}</td>
                  <td>{row.frame}</td>
                  <td>{row.run_id}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7}>{loading ? "불러오는 중" : "조건에 맞는 검출이 없습니다."}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
