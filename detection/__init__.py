"""TwinSight object detection, separate from tracking and spatial mapping."""

import os
from pathlib import Path

# Keep model runtime settings in the project rather than the user's global profile.
os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[1] / "runs" / ".ultralytics"))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
