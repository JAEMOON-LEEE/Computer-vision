import { latencyStats, useLive } from "../live";

function ms(value: number | null): string {
  return value === null ? "-" : value.toFixed(1);
}

export function LatencyPanel() {
  const { latencyRef, latencyTick, clearLatency } = useLive();
  const stats = latencyStats(latencyRef.current);
  void latencyTick;

  function printCsv() {
    const header = "camera_id,frame,timestamp,timestamp_kind,latency_ms,basis";
    const lines = latencyRef.current.map(
      (sample) =>
        `${sample.cameraId},${sample.frame},${sample.timestamp},${sample.timestampKind},${sample.latencyMs.toFixed(3)},${sample.basis}`,
    );
    console.log([header, ...lines].join("\n"));
  }

  return (
    <aside className="latency">
      <strong>지연</strong>
      <span>unix_seconds는 timestamp 기준, 그 외는 수신 시각 기준</span>
      <span>평균 {ms(stats.avg)} ms</span>
      <span>p95 {ms(stats.p95)} ms</span>
      <span>최대 {ms(stats.max)} ms</span>
      <span>n={stats.n}</span>
      <button type="button" onClick={printCsv}>
        CSV 콘솔 출력
      </button>
      <button type="button" onClick={clearLatency}>
        초기화
      </button>
    </aside>
  );
}
