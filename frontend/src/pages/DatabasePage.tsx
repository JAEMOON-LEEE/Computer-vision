import { useEffect, useState, type FormEvent } from "react";
import { databaseRequest, patchAlert } from "../api";

type RecordRow = Record<string, unknown>;
type Overview = { connected: boolean; engine: string; schema: string | null; tables: { name: string; label: string; count: number }[] };
type Records = { columns: string[]; items: RecordRow[]; total: number };
type CameraForm = { camera_id: string; name: string; lat: string; lon: string; status: string };
const EMPTY: CameraForm = { camera_id: "", name: "", lat: "", lon: "", status: "unknown" };
const text = (value: unknown) => value == null ? "" : String(value);
const display = (value: unknown) => value == null ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
const message = (error: unknown) => error instanceof Error ? error.message : "요청에 실패했습니다";

export function DatabasePage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [table, setTable] = useState("cameras");
  const [records, setRecords] = useState<Records | null>(null);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [overviewError, setOverviewError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<RecordRow | null>(null);
  const [camera, setCamera] = useState<CameraForm | null>(null);
  const [editing, setEditing] = useState(false);
  const [reference, setReference] = useState<{ run_id: string; origin_lat: string; origin_lon: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  useEffect(() => {
    let active = true;
    databaseRequest<Overview>("/overview").then(value => {
      if (active) { setOverview(value); setOverviewError(""); }
    }).catch(reason => { if (active) setOverviewError(message(reason)); });
    return () => { active = false; };
  }, [revision]);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setRecords(null); setSelected(null);
    const params = new URLSearchParams({ limit: "25", offset: String(offset), q: query });
    databaseRequest<Records>(`/tables/${table}?${params}`).then(value => {
      if (active) setRecords(value);
    }).catch(reason => { if (active) setError(message(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [table, offset, query, revision]);

  function refresh(note = "") {
    setNotice(note); setRevision(value => value + 1);
    window.dispatchEvent(new Event("twinsight-data-updated"));
  }
  function chooseTable(name: string) {
    setTable(name); setOffset(0); setDraft(""); setQuery(""); setNotice(""); setSelected(null);
  }
  function editCamera(row: RecordRow) {
    setCamera({ camera_id: text(row.camera_id), name: text(row.name), lat: text(row.lat), lon: text(row.lon), status: text(row.status) });
    setEditing(true); setFormError("");
  }
  async function saveCamera(event: FormEvent) {
    event.preventDefault(); if (!camera) return;
    setSaving(true); setFormError("");
    try {
      await databaseRequest(editing ? `/cameras/${encodeURIComponent(camera.camera_id)}` : "/cameras", {
        method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...camera, lat: camera.lat === "" ? null : Number(camera.lat), lon: camera.lon === "" ? null : Number(camera.lon) }),
      });
      setCamera(null); refresh("CCTV 정보를 저장했습니다.");
    } catch (reason) { setFormError(message(reason)); } finally { setSaving(false); }
  }
  async function saveReference(event: FormEvent) {
    event.preventDefault(); if (!reference) return;
    setSaving(true); setFormError("");
    try {
      await databaseRequest("/map-references", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...reference, origin_lat: Number(reference.origin_lat), origin_lon: Number(reference.origin_lon) }) });
      setReference(null); refresh("지도 기준점을 등록했습니다.");
    } catch (reason) { setFormError(message(reason)); } finally { setSaving(false); }
  }
  async function changeAlert(row: RecordRow, status: "confirmed" | "dismissed") {
    setSaving(true); setError("");
    try { await patchAlert(Number(row.id), status); refresh("경고 상태와 처리 이력을 저장했습니다."); }
    catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }

  return <main className="database-page">
    <div className="db-heading"><div><p className="db-eyebrow">데이터 관리</p><h1>프로젝트 데이터베이스</h1>
      <p className="meta">CCTV, 분석 결과, 지도 기준점과 산출물을 확인하고 관리합니다.</p></div>
      <div className="db-heading-actions"><span className={`db-connection ${overviewError ? "failed" : ""}`}>
        {overviewError ? "DB 연결 확인 필요" : overview ? `${overview.engine === "postgresql" ? "PostgreSQL" : "로컬 DB"} · ${overview.schema || "기본 스키마"}` : "DB 확인 중"}</span>
        <button onClick={() => refresh()} disabled={loading}>새로고침</button></div></div>
    {overviewError && <p className="err" role="alert">{overviewError}</p>}
    {notice && <p className="db-success" role="status">{notice}</p>}
    <div className="db-layout"><aside className="db-tables" aria-label="테이블 선택">
      {overview?.tables.map(item => <button key={item.name} className={table === item.name ? "active" : ""} onClick={() => chooseTable(item.name)}>
        <span><strong>{item.label}</strong><small>{item.name}</small></span><b>{item.count.toLocaleString()}</b></button>)}
    </aside><section className="db-content">
      <div className="db-toolbar"><h2>{overview?.tables.find(item => item.name === table)?.label || table}</h2>
        {table === "cameras" && <button className="db-primary" onClick={() => { setCamera({ ...EMPTY }); setEditing(false); setFormError(""); }}>CCTV 등록</button>}
        {table === "map_references" && <button className="db-primary" onClick={() => { setReference({ run_id: "", origin_lat: "", origin_lon: "" }); setFormError(""); }}>지도 기준점 등록</button>}
      </div>
      <form className="db-search" onSubmit={event => { event.preventDefault(); setOffset(0); setQuery(draft.trim()); }}>
        <label htmlFor="db-search">ID 검색</label><input id="db-search" value={draft} onChange={event => setDraft(event.target.value)} placeholder="CCTV·실행·산출물 ID" maxLength={200}/><button>검색</button>
        <span className="meta">{loading ? "불러오는 중…" : `${records?.total.toLocaleString() ?? 0}건`}</span>
      </form>
      {error && <p className="err" role="alert">{error}</p>}
      <div className="table-wrap db-grid" aria-busy={loading}><table><thead><tr><th>작업</th>{records?.columns.map(col => <th key={col}>{col}</th>)}</tr></thead>
        <tbody>{records?.items.map((row, index) => <tr key={index}>
          <td><div className="db-row-actions"><button onClick={() => setSelected(row)}>상세</button>
            {table === "cameras" && <button onClick={() => editCamera(row)}>수정</button>}
            {table === "runs" && <button onClick={() => { setReference({ run_id: text(row.run_id), origin_lat: "", origin_lon: "" }); setFormError(""); }}>기준점 등록</button>}
            {table === "alerts" && row.status === "unconfirmed" && <><button disabled={saving} onClick={() => void changeAlert(row, "confirmed")}>확인</button><button disabled={saving} onClick={() => void changeAlert(row, "dismissed")}>기각</button></>}
          </div></td>{records.columns.map(col => <td key={col} title={display(row[col])}><span className="db-cell">{display(row[col])}</span></td>)}</tr>)}
          {!records?.items.length && <tr><td colSpan={(records?.columns.length || 1) + 1} className="db-empty">{loading ? "데이터를 불러오고 있습니다." : error ? "조회에 실패했습니다. 새로고침으로 다시 시도하세요." : query ? "조건에 맞는 데이터가 없습니다." : "아직 저장된 데이터가 없습니다. 수집된 결과는 이곳에 표시됩니다."}</td></tr>}
        </tbody></table></div>
      <div className="pager"><button disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 25))}>이전</button>
        <span>{records?.total ? `${offset + 1}–${offset + records.items.length} / ${records.total.toLocaleString()}` : "0건"}</span>
        <button disabled={loading || offset + 25 >= (records?.total || 0)} onClick={() => setOffset(value => value + 25)}>다음</button></div>
    </section></div>
    {selected && <div className="db-modal-backdrop"><section className="db-modal" role="dialog" aria-modal="true" aria-label="레코드 상세"><div className="db-toolbar"><h2>레코드 상세</h2><button autoFocus onClick={() => setSelected(null)}>닫기</button></div><pre>{JSON.stringify(selected, null, 2)}</pre></section></div>}
    {camera && <div className="db-modal-backdrop"><form className="db-modal" role="dialog" aria-modal="true" aria-label={editing ? "CCTV 수정" : "CCTV 등록"} onSubmit={saveCamera}>
      <h2>{editing ? "CCTV 정보 수정" : "CCTV 등록"}</h2>
      <label>CCTV ID<input autoFocus required disabled={editing} pattern="[A-Za-z0-9_.:\-]+" maxLength={128} value={camera.camera_id} onChange={e => setCamera({ ...camera, camera_id: e.target.value })}/></label>
      <label>이름<input required maxLength={256} value={camera.name} onChange={e => setCamera({ ...camera, name: e.target.value })}/></label>
      <div className="db-form-pair"><label>위도<input type="number" step="any" min={-90} max={90} value={camera.lat} onChange={e => setCamera({ ...camera, lat: e.target.value })}/></label>
      <label>경도<input type="number" step="any" min={-180} max={180} value={camera.lon} onChange={e => setCamera({ ...camera, lon: e.target.value })}/></label></div>
      <p className="meta">위도·경도를 모두 입력하면 CCTV 지도에 위치를 표시할 수 있습니다.</p>
      <label>상태<input required maxLength={32} value={camera.status} onChange={e => setCamera({ ...camera, status: e.target.value })}/></label>
      {formError && <p className="err" role="alert">{formError}</p>}
      <div className="db-toolbar"><button type="button" disabled={saving} onClick={() => setCamera(null)}>취소</button><button className="db-primary" disabled={saving}>{saving ? "저장 중…" : "저장"}</button></div>
    </form></div>}
    {reference && <div className="db-modal-backdrop"><form className="db-modal" role="dialog" aria-modal="true" aria-label="지도 기준점 등록" onSubmit={saveReference}>
      <h2>지도 기준점 등록</h2><p className="meta">기존 분석 실행에 기준 위경도를 등록합니다. 과거 경로가 달라지지 않도록 등록된 기준점은 변경하지 않습니다.</p>
      <label>실행 ID<input autoFocus required value={reference.run_id} onChange={e => setReference({ ...reference, run_id: e.target.value })}/></label>
      <label>기준 위도<input required type="number" step="any" min={-84.999999} max={84.999999} value={reference.origin_lat} onChange={e => setReference({ ...reference, origin_lat: e.target.value })}/></label>
      <label>기준 경도<input required type="number" step="any" min={-180} max={180} value={reference.origin_lon} onChange={e => setReference({ ...reference, origin_lon: e.target.value })}/></label>
      {formError && <p className="err" role="alert">{formError}</p>}
      <div className="db-toolbar"><button type="button" disabled={saving} onClick={() => setReference(null)}>취소</button><button className="db-primary" disabled={saving}>{saving ? "등록 중…" : "등록"}</button></div>
    </form></div>}
  </main>;
}
