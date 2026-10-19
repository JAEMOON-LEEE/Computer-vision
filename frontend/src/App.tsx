import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { AlertDrawer } from "./components/AlertDrawer";
import { useLive } from "./live";
import { HistoryPage } from "./pages/HistoryPage";
import { MonitorPage } from "./pages/MonitorPage";

export function App() {
  const { wsStatus, alerts } = useLive();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const unconfirmed = alerts.filter((alert) => alert.status === "unconfirmed").length;
  const connected = wsStatus.startsWith("실시간");
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
          </nav>
        </div>
        <div className="top-actions">
          <span className={connected ? "ws-dot on" : "ws-dot"} title={wsStatus} />
          <button type="button" className="alert-badge" onClick={() => setDrawerOpen(true)}>
            미확인
            <b>{unconfirmed}</b>
          </button>
        </div>
      </header>
      <Routes>
        <Route path="/" element={<MonitorPage />} />
        <Route path="/history" element={<HistoryPage />} />
      </Routes>
      <AlertDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}
