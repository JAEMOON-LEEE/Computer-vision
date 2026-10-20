export type Camera = {
  camera_id: string;
  name: string | null;
  source: string;
  lat: number | null;
  lon: number | null;
  stream_url: string | null;
  stream_fetched_at: string | null;
  image_width: number | null;
  image_height: number | null;
  is_ptz: boolean;
  status: string;
  created_at: string;
};

export type StreamInfo = {
  camera_id: string;
  stream_url: string;
  stream_fetched_at: string | null;
  refreshed: boolean;
  warning: string | null;
};

export type Detection = {
  class_name: string;
  class_id: number;
  category_id: number;
  model_id: string;
  bbox_xyxy: number[];
  confidence: number;
  track_id: number | null;
  ground_point_px?: number[] | null;
  mapped_xz?: number[] | null;
};

export type FrameRecord = {
  camera_id: string;
  frame: number;
  timestamp: number;
  timestamp_kind: string;
  width: number;
  height: number;
  inference_ms?: number;
  detections: Detection[];
};

export type LatestFrame = FrameRecord & {
  run_id: string;
  image: string | null;
};

export type AlertItem = {
  id: number;
  run_id: string;
  alert_id: string;
  camera_id: string;
  frame: number;
  timestamp: number;
  type: string;
  severity: string;
  status: string;
  message: string;
  evidence: Record<string, unknown>[];
  basis: string;
  created_at: string;
  updated_at: string;
  handled_by: string | null;
};

export type DetectionHistoryItem = {
  camera_id: string;
  run_id: string;
  frame: number;
  timestamp: number;
  timestamp_kind: string;
  width: number;
  height: number;
  inference_ms: number;
  image: string | null;
  class_name: string;
  class_id: number;
  category_id: number;
  model_id: string;
  bbox_xyxy: number[];
  confidence: number;
  track_id: number | null;
  ground_point_px: number[] | null;
  mapped_xz: number[] | null;
};

export type DetectionList = {
  total: number;
  items: DetectionHistoryItem[];
};

export type DetectionStats = {
  by_class: { class_name: string; count: number }[];
  by_hour: { hour: string; count: number }[];
};

export type LatencySample = {
  cameraId: string;
  frame: number;
  timestamp: number;
  timestampKind: string;
  latencyMs: number;
  basis: "timestamp" | "received";
};

export type OverlayState = {
  cameraId: string;
  width: number;
  height: number;
  boxes: Detection[];
  updatedAt: number;
  timestamp: number;
  timestampKind: string;
  frame: number;
  pendingMeasure: boolean;
};

export const CLASSES = [
  "person",
  "car",
  "truck",
  "bus",
  "motorcycle",
  "bicycle",
  "pothole",
  "crack",
  "debris",
  "barrier",
] as const;

export const DEFAULT_CAMERA = "its-cc4277cc18";
