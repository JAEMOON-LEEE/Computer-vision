// A shared server serves the dashboard and API from the same origin.
// Port 5173 retains the local standalone frontend development workflow.
window.TWINSIGHT_API = (window.TWINSIGHT_API_BASE || (
  location.port === "5173" ? `${location.protocol}//${location.hostname}:8000` : location.origin
)).replace(/\/$/, "");
