import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import { databaseRequest } from "../api";
import { MAP_TILES } from "../components/CameraMap";

type Result = { source: "detections" | "ground_truth"; record_id: string; title: string; kind: string; origin: string; status: string; created_at: string; frames: number };
type Frame = { source: "detections" | "ground_truth"; stream: string; line_no: number; camera_id: string; frame: number; timestamp: number | null; width: number; height: number; detections: { world_xz: number[] | null; class_name: string; confidence: number | null; bbox_xyxy: number[] }[]; camera_location: { lat: number; lon: number } | null; map_notice: string };
const resultKey = (r: Result) => `${r.source}:${r.record_id}`;
const errorText = (e: unknown) => e instanceof Error ? e.message : "조회 실패";

export function SavedResultsPage() {
  const [results, setResults] = useState<Result[]>([]);
  const [id, setId] = useState("");
  const [offset, setOffset] = useState(0);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const selected = results.find(r => resultKey(r) === id);
  useEffect(() => {
    let active = true;
    setListError("");
    setResults([]); setId(""); setOffset(0);
    databaseRequest<{ items: Result[]; total: number }>(`/saved-results/search?${new URLSearchParams({ q: search, offset: String(page * 25), limit: "25" })}`).then(data => {
      if (active) { setResults(data.items); setTotal(data.total); setId(data.items[0] ? resultKey(data.items[0]) : ""); }
    }).catch(e => { if (active) setListError(errorText(e)); });
    return () => { active = false; };
  }, [revision, search, page]);
  useEffect(() => {
    let active = true;
    setFrame(null); setError("");
    if (!selected) return;
    setLoading(true);
    databaseRequest<Frame>(`/saved-results/frame?${new URLSearchParams({ record_id: selected.record_id, source: selected.source, offset: String(offset) })}`)
      .then(value => { if (active) setFrame(value); })
      .catch(e => { if (active) setError(errorText(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [selected?.record_id, selected?.source, offset, revision]);
  return <main className="database-page">
    <div className="db-heading"><div><h1>팀원 저장 결과</h1><p>DB에 보관된 실험·검출 로그를 프레임별로 확인합니다. 실시간 경고와 별도로 표시합니다.</p></div><button onClick={() => setRevision(v => v + 1)}>새로고침</button></div>
    {listError && <p className="err" role="alert">{listError}</p>}
    <form onSubmit={e => { e.preventDefault(); setSearch(query); setPage(0); }}><label>작업 검색 <input value={query} maxLength={200} onChange={e => setQuery(e.target.value)} placeholder="작업 이름 또는 ID"/></label><button type="submit">검색</button></form>
    <div className="pager"><button disabled={page === 0} onClick={() => setPage(v => v - 1)}>이전 목록</button><span>총 {total}개 · {page + 1} / {Math.max(1, Math.ceil(total / 25))} 페이지</span><button disabled={(page + 1) * 25 >= total} onClick={() => setPage(v => v + 1)}>다음 목록</button></div>
    <label>작업 선택 <select style={{ maxWidth: "100%" }} value={id} onChange={e => { setId(e.target.value); setOffset(0); }}>
      {results.map(r => <option key={resultKey(r)} value={resultKey(r)}>{r.source === "ground_truth" ? "[가상환경 정답] " : "[검출] "}{r.title} · {r.frames.toLocaleString()}프레임</option>)}
    </select></label>
    {!selected && <p>표시할 저장 결과가 없거나 불러오는 중입니다.</p>}
    {selected && <>
      <div className="kpi-grid"><article className="kpi"><small>데이터 출처</small><strong>{({ real: "실제 영상", synthetic: "시뮬레이션", mixed: "혼합" } as Record<string, string>)[selected.origin] || selected.origin}</strong></article><article className="kpi"><small>저장 프레임</small><strong>{selected.frames.toLocaleString()}</strong></article><article className="kpi"><small>작업 상태</small><strong>{selected.status}</strong></article><article className="kpi"><small>현재 프레임 객체</small><strong>{frame?.detections.length ?? "—"}</strong></article></div>
      <p className="meta">등록: {new Date(selected.created_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} KST · {selected.kind}</p>
      <div className="pager"><button disabled={offset === 0} onClick={() => setOffset(v => v - 1)}>이전</button><label>프레임 {offset + 1} / {selected.frames} <input aria-label="저장 프레임 선택" type="range" min={0} max={selected.frames - 1} value={offset} onChange={e => setOffset(Number(e.target.value))}/></label><button disabled={offset + 1 >= selected.frames} onClick={() => setOffset(v => v + 1)}>다음</button></div>
      {loading && <p role="status">프레임을 불러오는 중…</p>}{error && <p className="err" role="alert">{error}</p>}
      {frame && <><p>{frame.camera_id} · 프레임 {frame.frame} · 영상 시간 {frame.timestamp ?? "—"}초</p><p className="meta">{frame.stream} / 로그 {frame.line_no}</p>
        <div className="twin-split"><section className="panel-card"><h2>{frame.source === "ground_truth" ? "정답 객체" : "검출 객체"} · 영상 좌표</h2><p>원본 영상 없이 저장된 상자를 표시합니다.</p>
          <svg viewBox={`0 0 ${frame.width} ${frame.height}`} style={{ width: "100%", maxHeight: 420, background: "#101c2b" }} role="img" aria-label="저장된 검출 상자와 클래스">
            {frame.detections.map((d, i) => <g key={i}><rect x={d.bbox_xyxy[0]} y={d.bbox_xyxy[1]} width={d.bbox_xyxy[2] - d.bbox_xyxy[0]} height={d.bbox_xyxy[3] - d.bbox_xyxy[1]} fill="none" stroke="#53dbc0" strokeWidth={2}/><text x={d.bbox_xyxy[0]} y={Math.max(12, d.bbox_xyxy[1] - 4)} fill="white" fontSize={12}>{d.class_name}</text></g>)}
          </svg>{!frame.detections.length && <p>이 프레임에는 검출 객체가 없습니다.</p>}</section>
          <section className="panel-card">{frame.source === "ground_truth" ? <VirtualMap frame={frame}/> : <><h2>촬영 위치 지도</h2><p>{frame.map_notice}</p>
            {frame.camera_location ? <MapContainer key={`${frame.camera_location.lat},${frame.camera_location.lon}`} center={[frame.camera_location.lat, frame.camera_location.lon]} zoom={16} style={{ height: 350 }}><TileLayer {...MAP_TILES}/><CircleMarker center={[frame.camera_location.lat, frame.camera_location.lon]}><Tooltip permanent>{frame.camera_id} · 카메라 위치</Tooltip></CircleMarker></MapContainer> : <p>카메라 위경도가 아직 등록되지 않았습니다. <Link to="/database">DB 관리</Link>에서 CCTV ID <code>{frame.camera_id}</code>와 확인된 위치를 등록하면 지도에 표시됩니다.</p>}
          </>}</section></div>
        <div className="table-wrap"><table><thead><tr><th>객체</th><th>신뢰도</th><th>영상 좌표</th></tr></thead><tbody>{frame.detections.map((d, i) => <tr key={i}><td>{d.class_name}</td><td>{d.confidence == null ? "—" : `${(d.confidence * 100).toFixed(1)}%`}</td><td>{d.bbox_xyxy.map(v => v.toFixed(1)).join(", ")}</td></tr>)}</tbody></table></div>
      </>}
      <RecordDetails key={`${selected.record_id}:${revision}`} recordId={selected.record_id}/>
    </>}
  </main>;
}

function RecordDetails({ recordId }: { recordId: string }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<unknown>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let active = true;
    setError("");
    databaseRequest(`/saved-results/record?${new URLSearchParams({ record_id: recordId })}`)
      .then(data => { if (active) setValue(data); })
      .catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; };
  }, [open, recordId]);
  return <details onToggle={e => setOpen(e.currentTarget.open)}><summary>저장된 작업 요약·보정 연결</summary>
    {error ? <p className="err" role="alert">{error}</p> : <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{value === null ? "불러오는 중…" : JSON.stringify(value, null, 2)}</pre>}
  </details>;
}

function VirtualMap({ frame }: { frame: Frame }) {
  const points = frame.detections.filter(d => d.world_xz !== null);
  const xs = points.map(d => d.world_xz![0]), zs = points.map(d => d.world_xz![1]);
  const minX = Math.min(0, ...xs) - 5, maxX = Math.max(0, ...xs) + 5;
  const minZ = Math.min(0, ...zs) - 5, maxZ = Math.max(0, ...zs) + 5;
  const span = Math.max(maxX - minX, maxZ - minZ);
  const px = (x: number) => 30 + (x - minX) / span * 440;
  const py = (z: number) => 470 - (z - minZ) / span * 440;
  return <><h2>가상환경 평면도 · X/Z</h2><p>Unity 정답 위치 · 단위 m · 위쪽 +Z, 오른쪽 +X. 검출로 추정한 위치가 아닙니다.</p>
    {!points.length ? <p>이 프레임에 표시할 가상 좌표가 없습니다.</p> : <svg viewBox="0 0 500 500" style={{ width: "100%", maxHeight: 420, background: "#101c2b" }} role="img" aria-label="가상환경 정답 위치 평면도">
      <path d={`M ${px(0)} 10 V 480 M 20 ${py(0)} H 490`} stroke="#62748c" fill="none"/>
      <text x="30" y="20" fill="white" fontSize="12">+Z ↑ · +X → · 현재 범위 {span.toFixed(1)} m</text>
      <text x={px(0) + 5} y={py(0) - 5} fill="#aab6c8" fontSize="12">원점</text>
      {points.map((d, i) => <g key={i}><circle cx={px(d.world_xz![0])} cy={py(d.world_xz![1])} r="5" fill="#53dbc0"/><text x={px(d.world_xz![0]) + 7} y={py(d.world_xz![1]) - 7} fill="white" fontSize="11">{d.class_name}<title>{d.world_xz!.map(v => v.toFixed(2)).join(", ")} m</title></text></g>)}
    </svg>}
    <p className="meta">프레임별 자동 범위 · 실제 위경도 지도와 별개인 시뮬레이션 좌표입니다.</p></>;
}
