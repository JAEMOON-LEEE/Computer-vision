"""지도·경로·위험 이력 통합 시연. 실제 CCTV/ITS를 호출하지 않는 명시적 합성 데이터."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import httpx


def seed(client, run_id: str):
    camera = "demo-map"
    def send(path, body, method="post"):
        response = getattr(client, method)(path, json=body)
        response.raise_for_status()
        return response.json()
    send("/cameras", {"camera_id": camera, "name": "지도 시연 (합성 데이터)",
                      "source": "synthetic", "lat": 37.5665, "lon": 126.9780})
    frames = []
    for n in range(30):
        def item(name, model, track, position):
            return {"class_name": name, "class_id": 2 if name == "car" else 0,
                    "category_id": 1 if name == "car" else 6, "model_id": model,
                    "track_id": track, "confidence": 0.9, "bbox_xyxy": [10, 10, 30, 30],
                    "ground_point_px": [20, 30], "mapped_xz": position,
                    "mapped_xz_corrected": [position[0] + 0.2, position[1] + 0.4]}
        frames.append({"camera_id": camera, "frame": n, "timestamp": n * 0.2,
                       "timestamp_kind": "simulation_seconds", "width": 640, "height": 360,
                       "inference_ms": 0, "detections": [item("car", "primary", 1, [n, n * 2]),
                                                                        item("pothole", "road", 1, [20, 25])]})
    send("/ingest/detections?run_id=" + run_id, frames)
    send(f"/runs/{run_id}/map-reference", {"coordinate_system": "local_enu", "units": "m",
                                          "origin_lat": 37.5665, "origin_lon": 126.9780}, "put")
    result = send("/ingest/alerts?run_id=" + run_id, {
        "camera_id": camera, "alert_id": "demo-map:1", "frame": 10, "timestamp": 2,
        "type": "road_damage", "severity": "warning", "status": "unconfirmed",
        "message": "합성 포트홀 경고 — 실제 도로 위험 아님", "basis": "synthetic_demo",
        "evidence": [{"class_name": "pothole", "model_id": "road", "track_id": 1}],
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    run = "map-demo-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    with httpx.Client(base_url=args.api, timeout=30) as client:
        seed(client, run)
    print(f"합성 시연 생성: camera=demo-map run={run}")
    print("http://localhost:5173/frontend/ 에서 지도 시연 (합성 데이터) 카메라를 선택하세요.")


if __name__ == "__main__":
    main()
