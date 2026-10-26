import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { AlertDrawer } from "./components/AlertDrawer";
import { formatKstClock } from "./format";
import { useLive } from "./live";
import { AnalysisPage } from "./pages/AnalysisPage";
import { HistoryPage } from "./pages/HistoryPage";
import { DatabasePage } from "./pages/DatabasePage";
import { MonitorPage } from "./pages/MonitorPage";

export function App() {
  const { wsStatus, unconfirmedAlerts } = useLive();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [clock, setClock] = useState(() => formatKstClock());
  const unconfirmed = unconfirmedAlerts.length;
  const connected = wsStatus.startsWith("실시간");

  useEffect(() => {
    const timer = window.setInterval(() => setClock(formatKstClock()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <strong>TwinSight</strong>
          <nav>
            <NavLink to="/" end>
              관제
            </NavLink>
            <NavLink to="/history">이력</NavLink>
            <NavLink to="/analysis">분석</NavLink>
            <NavLink to="/database">DB 관리</NavLink>
          </nav>
        </div>
        <div className="top-actions">
          <span className="ws-label" title={wsStatus}>
            <span className={connected ? "ws-dot on" : "ws-dot"} />
            {connected ? "실시간 연결" : "연결 끊김"}
          </span>
          <time className="kst-clock">{clock} KST</time>
          <button type="button" className="alert-badge" onClick={() => setDrawerOpen(true)}>
            <BellIcon />
            미확인 경고 {unconfirmed}
          </button>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<MonitorPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/database" element={<DatabasePage />} />
      </Routes>
      <AlertDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="bell">
      <path d="M6 9a6 6 0 1 1 12 0c0 7 2 7 2 7H4s2 0 2-7" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </svg>
  );
}
