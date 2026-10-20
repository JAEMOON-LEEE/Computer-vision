import json

import pytest
from sqlalchemy import inspect

from backend.scripts.catalog import export_record, load_manifest, prepare, register


def record(key="dataset-v1", **changes):
    return {"record_id": key, "kind": "dataset", "title": "합성 학습 자료", "owner": "이상민",
            "data_origin": "synthetic", "status": "completed", "parents": [], "details": {}, **changes}


def add(client, key="dataset-v1", **changes):
    response = client.post("/catalog/records", json=record(key, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def test_pipeline_lineage_and_real_synthetic_separation(client):
    assert client.post("/cameras", json={"camera_id": "cctv-1"}).status_code == 200
    parent = None
    for i, kind in enumerate(("cctv_info", "calibration", "simulation", "capture", "dataset", "training", "model", "evaluation")):
        key = f"stage-{i}"
        add(client, key, kind=kind, camera_id="cctv-1", parents=[parent] if parent else [],
            data_origin="real" if i < 2 or kind == "evaluation" else "synthetic")
        parent = key
    graph = client.get("/catalog/records/stage-7/lineage").json()
    assert len(graph["records"]) == 8
    assert len(graph["edges"]) == 7
    assert not graph["truncated"]
    reverse = client.get("/catalog/records/stage-0/lineage?direction=descendants").json()
    assert len(reverse["records"]) == 8
    page = client.get("/catalog/records?data_origin=real").json()
    assert len(page["items"]) == 3
    limited = client.get("/catalog/records/stage-7/lineage?limit=2").json()
    assert len(limited["records"]) == 2 and limited["truncated"]


def test_immutable_versions_and_parent_order_idempotence(client):
    add(client, "a")
    add(client, "b")
    add(client, "model-v1", kind="model", parents=["a", "b"])
    add(client, "model-v1", kind="model", parents=["b", "a"])
    assert client.post("/catalog/records", json=record("a", title="different")).status_code == 409
    assert client.post("/catalog/records", json=record("a", parents=["model-v1"])).status_code == 409
    assert client.post("/catalog/records", json=record("missing-parent", parents=["absent"])).status_code == 422
    assert client.post("/catalog/records", json=record("self", parents=["self"])).status_code == 422


def test_camera_and_detection_run_identity(client):
    from backend.tests.test_api import frame_record
    assert client.post("/ingest/detections?run_id=r", json=frame_record(camera_id="a")).status_code == 200
    assert client.post("/catalog/records", json=record(camera_id="unknown")).status_code == 422
    assert client.post("/catalog/records", json=record(detection_run_id="r")).status_code == 422
    add(client, kind="detection", camera_id="a", detection_run_id="r")


def test_files_idempotent_conflicts_and_batch_rollback(client):
    add(client)
    path = "/catalog/records/dataset-v1/files"
    file = {"path": "weights/best.pt", "size_bytes": 5_000_000_000, "sha256": "a" * 64, "role": "model"}
    assert client.post(path, json=[file, file]).json() == {"saved": 1, "ignored": 1}
    assert client.post(path, json=[{**file, "path": "new.pt"}, {**file, "sha256": "b" * 64}]).status_code == 409
    rows = client.get(path).json()["items"]
    assert len(rows) == 1 and rows[0]["size_bytes"] == 5_000_000_000


@pytest.mark.parametrize("value", ["../secret", "/root/data", "C:/data", "a\\b", "a//b", "."])
def test_invalid_artifact_paths(client, value):
    add(client)
    response = client.post("/catalog/records/dataset-v1/files", json=[
        {"path": value, "size_bytes": 1, "sha256": "a" * 64, "role": "file"}])
    assert response.status_code == 422


def test_log_pages_and_immutable_lines(client):
    add(client)
    path = "/catalog/records/dataset-v1/logs"
    rows = [{"stream": "train.log", "line_no": i, "message": f"epoch {i} 완료"} for i in range(1, 4)]
    assert client.post(path, json=rows).json()["saved"] == 3
    assert client.post(path, json=rows).json()["ignored"] == 3
    page = client.get(path + "?limit=2").json()
    assert len(page["items"]) == 2
    assert client.get(path, params={"after_id": page["next_after_id"]}).json()["items"][0]["line_no"] == 3
    assert client.get(path + "?stream=other").json()["items"] == []
    assert client.post(path, json=[{**rows[0], "message": "changed"}]).status_code == 409


def test_record_pagination(client):
    for key in ("a", "b", "c"):
        add(client, key)
    page = client.get("/catalog/records?limit=2").json()
    assert page["next_after_id"] == "b"
    assert client.get("/catalog/records?after_id=b").json()["items"][0]["record_id"] == "c"


def test_prepare_register_verify_export_roundtrip(client, tmp_path):
    source = tmp_path / "training"
    source.mkdir()
    (source / "metrics.json").write_text('{"mAP50": 0.8}')
    (source / "results.csv").write_text('epoch, metrics/mAP50(B)\n1,0.5\n2,0.8\n')
    (source / "train.log").write_text("epoch 1\nepoch 2 완료\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=do-not-upload")
    manifest = tmp_path / "manifest.json"
    assert prepare(source, record(kind="training"), manifest)["files"] == 3
    body = json.loads(manifest.read_text(encoding="utf-8"))
    assert body["record"]["details"]["metric_summaries"]["results.csv"]["last_row"]["epoch"] == 2
    assert register(client, manifest)["log_lines"] == 2
    assert register(client, manifest)["log_lines"] == 2
    export_record(client, "dataset-v1", tmp_path / "export")
    assert (tmp_path / "export/export-complete.json").exists()
    assert len((tmp_path / "export/logs.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    (source / "train.log").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        load_manifest(manifest)


def test_invalid_log_is_rejected_before_any_api_write(client, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "train.log").write_text("x" * 16385)
    manifest = tmp_path / "manifest.json"
    prepare(source, record(), manifest)
    with pytest.raises(ValueError):
        register(client, manifest)
    assert client.get("/catalog/records").json()["items"] == []


def test_schema_upgrade_preserves_existing_camera(client):
    from backend.app import db
    from backend.app.catalog_models import CatalogFile, CatalogLog, CatalogParent, CatalogRecord
    client.post("/cameras", json={"camera_id": "preserve"})
    for model in (CatalogLog, CatalogFile, CatalogParent, CatalogRecord):
        model.__table__.drop(db.engine)
    db.init_db()
    db.init_db()
    assert "catalog_records" in inspect(db.engine).get_table_names()
    assert client.get("/cameras/preserve").status_code == 200
    add(client)


def test_camera_snapshots_preserve_history_without_stream_secrets(client):
    body = {"camera_id": "its-one", "source": "ITS", "lat": 37, "lon": 127,
            "stream_url": "https://example.test/video?secret=PRIVATE"}
    assert client.post("/cameras", json=body).status_code == 200
    assert client.post("/cameras", json=body).status_code == 200
    assert client.post("/cameras", json={**body, "lat": 38}).status_code == 200
    page = client.get("/catalog/records?kind=cctv_info&camera_id=its-one").json()
    assert len(page["items"]) == 2
    assert {r["details"]["lat"] for r in page["items"]} == {37, 38}
    assert "PRIVATE" not in json.dumps(page)
    assert all(r["data_origin"] == "real" for r in page["items"])


def test_log_snapshot_stays_consistent_if_source_changes_during_http(client, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    log = source / "train.log"
    log.write_text("original\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    prepare(source, record(), manifest)

    class ChangingClient:
        def post(self, path, **kwargs):
            if path == "/catalog/records":
                log.write_text("new content\n", encoding="utf-8")
            return client.post(path, **kwargs)

    register(ChangingClient(), manifest)
    logs = client.get("/catalog/records/dataset-v1/logs").json()["items"]
    assert logs[0]["message"] == "original"
    with pytest.raises(ValueError, match="changed"):
        load_manifest(manifest)
