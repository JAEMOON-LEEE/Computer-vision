"""카메라 정보의 변경 이력. 서명 스트림 URL과 API 키는 카탈로그에 복제하지 않는다."""
import hashlib
import json

from backend.app.catalog_models import CatalogRecord


def snapshot_camera(db, camera, road_type=None):
    db.flush()
    fields = ("camera_id", "name", "source", "lat", "lon", "image_width", "image_height", "is_ptz", "status")
    details = {key: getattr(camera, key) for key in fields}
    if road_type is not None:
        details["road_type"] = road_type
    digest = hashlib.sha256(json.dumps(details, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    key = "cctv-" + digest
    if db.get(CatalogRecord, key) is not None:
        return key
    body = {"record_id": key, "kind": "cctv_info", "title": f"CCTV 정보: {camera.camera_id}"[:256],
            "owner": "CCTV API 수집", "camera_id": camera.camera_id, "detection_run_id": None,
            "data_origin": "real" if camera.source == "ITS" else "synthetic" if camera.source == "synthetic" else "unspecified",
            "status": "completed", "details": details, "parents": []}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    db.add(CatalogRecord(**{k: v for k, v in body.items() if k != "parents"}, fingerprint=fingerprint))
    db.flush()
    return key
