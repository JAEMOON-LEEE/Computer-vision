"""지금 앱의 OpenAPI 스키마를 docs/api/openapi.json으로 저장한다.

저장소 루트에서:
    .\\.venv\\Scripts\\python.exe backend\\scripts\\export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402


def main() -> int:
    spec = app.openapi()
    path = ROOT / "docs" / "api" / "openapi.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장함 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
