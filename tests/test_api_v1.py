import pytest

from conftest import make_app, task_doc, workflow_doc
from dagonservice.config import Settings


def create(client, doc=None):
    response = client.post("/api/v1/workflows", json=doc or workflow_doc())
    assert response.status_code == 201
    return response.get_json()


def test_health_and_info(client):
    health = client.get("/api/v1/health").get_json()
    assert health["status"] == "ok" and health["database"] == "ok"
    info = client.get("/api/v1/info").get_json()
    assert info["statuses"] == ["READY", "WAITING", "RUNNING", "FINISHED", "FAILED"]
    assert "mongo_uri" not in info["settings"]


def test_list_filters_and_pagination(client):
    first = create(client, workflow_doc("One"))
    create(client, workflow_doc("Two"))
    client.put("/api/v1/workflows/%s/tasks/A/status" % first["id"], json={"status": "FAILED"})
    listing = client.get("/api/v1/workflows").get_json()
    assert listing["total"] == 2 and "tasks" not in listing["items"][0]
    failed = client.get("/api/v1/workflows?status=failed").get_json()
    assert [item["name"] for item in failed["items"]] == ["One"]
    assert client.get("/api/v1/workflows?name=Two").get_json()["total"] == 1
    assert len(client.get("/api/v1/workflows?limit=1").get_json()["items"]) == 1
    assert client.get("/api/v1/workflows?limit=-1").status_code == 400
    assert client.get("/api/v1/workflows?status=nope").status_code == 400


def test_status_and_patch(client):
    wid = create(client)["id"]
    task = client.put("/api/v1/workflows/%s/tasks/A/status" % wid, json={"status": "running"}).get_json()
    assert task["status"] == "RUNNING"
    patched = client.patch("/api/v1/workflows/%s/tasks/A" % wid, json={"working_dir": "/w/A", "slurm_job": "42"})
    assert patched.get_json()["working_dir"] == "/w/A"
    assert client.patch("/api/v1/workflows/%s/tasks/A" % wid, json={"prevs": []}).status_code == 400
    assert client.put("/api/v1/workflows/%s/tasks/A/status" % wid, json={}).status_code == 400


def test_events_are_incremental(client):
    wid = create(client)["id"]
    first = client.get("/api/v1/workflows/%s/events" % wid).get_json()
    assert [event["kind"] for event in first["items"]] == ["workflow.created"]
    client.put("/changestatus/%s/A/RUNNING" % wid)
    client.put("/%s/B/dependency/A" % wid)
    later = client.get("/api/v1/workflows/%s/events?after=%s" % (wid, first["last"])).get_json()
    assert [event["kind"] for event in later["items"]] == ["task.status", "task.dependency"]
    assert later["items"][0]["status"] == "RUNNING"


def test_graph_marks_transversal_and_explicit_edges(client):
    doc = workflow_doc(tasks=("A", "B", "C"))
    doc["tasks"]["C"]["explicit_prevs"] = ["B"]
    wid = create(client, doc)["id"]
    client.put("/%s/B/dependency/A" % wid)
    client.put("/%s/C/dependency/B" % wid)
    client.put("/%s/A/dependency/External" % wid)
    graph = client.get("/api/v1/workflows/%s/graph" % wid).get_json()
    edges = {(edge["source"], edge["target"]): edge for edge in graph["edges"]}
    assert edges[("B", "C")]["kind"] == "explicit"
    assert edges[("A", "B")]["kind"] == "dependency"
    assert edges[("External", "A")]["transversal"] is True


def test_document_round_trip_keeps_dagonstar_fields(client):
    doc = workflow_doc(tasks=("A",))
    doc["pre_stage"] = True
    doc["dagonweb"] = {"layout": {"A": [10, 20]}}
    doc["tasks"]["A"]["function"] = "module:callable"
    wid = create(client, doc)["id"]
    client.put("/changestatus/%s/A/FINISHED" % wid)
    exported = client.get("/api/v1/workflows/%s/document" % wid).get_json()
    assert exported["id"] == wid and exported["pre_stage"] is True
    assert exported["dagonweb"] == {"layout": {"A": [10, 20]}}
    task = exported["tasks"]["A"]
    assert task["function"] == "module:callable"
    assert "history" not in task and "updated_at" not in task
    download = client.get("/api/v1/workflows/%s/document?download=1" % wid)
    assert 'filename="Example.json"' in download.headers["Content-Disposition"]


def test_add_task_and_by_name(client):
    wid = create(client, workflow_doc(tasks=()))["id"]
    assert client.post("/api/v1/workflows/%s/tasks" % wid, json=task_doc("X")).status_code == 201
    assert client.get("/api/v1/workflows/by-name/Example").get_json()["id"] == wid
    assert client.get("/api/v1/workflows/%s/tasks/X" % wid).get_json()["workflow"] == "Example"
    assert client.delete("/api/v1/workflows/%s" % wid).status_code == 200
    assert client.get("/api/v1/workflows/%s" % wid).status_code == 404


def test_history_is_capped():
    client = make_app(max_history=3).test_client()
    wid = create(client)["id"]
    for status in ("WAITING", "RUNNING", "FAILED", "READY", "RUNNING"):
        client.put("/changestatus/%s/A/%s" % (wid, status))
    history = client.get("/%s/A" % wid).get_json()["task"]["history"]
    assert [item["status"] for item in history] == ["FAILED", "READY", "RUNNING"]


def test_token_protects_mutations_only_by_default():
    client = make_app(api_token="s3cret").test_client()
    assert client.post("/create", json=workflow_doc()).status_code == 401
    response = client.post("/create", json=workflow_doc(), headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 201
    assert client.get("/list").status_code == 200
    assert client.head("/check").status_code == 200
    assert client.post("/create", json=workflow_doc(), headers={"X-API-Key": "wrong"}).status_code == 401


def test_token_can_protect_reads():
    client = make_app(api_token="s3cret", protect_reads=True).test_client()
    assert client.get("/list").status_code == 401
    assert client.get("/list", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/v1/health").status_code == 200


def test_dashboard_and_security_headers(client):
    page = client.get("/")
    assert page.status_code == 200 and b"DAGonService" in page.data
    assert "script-src 'self'" in page.headers["Content-Security-Policy"]
    assert client.get("/static/dashboard.js").status_code == 200
    disabled = make_app(dashboard=False).test_client().get("/").get_json()
    assert disabled["api"] == "/api/v1"


def test_settings_from_env():
    settings = Settings.from_env({"MONGO_DB": "dagon_mongodb", "DAGONSERVICE_WEBHOOK_URLS": "http://a, http://b"})
    assert settings.mongo_uri == "mongodb://dagon_mongodb:27017"
    assert settings.webhook_urls == ["http://a", "http://b"]
    assert Settings.from_env({"DAGONSERVICE_MONGO_URI": "mongodb://m/"}).mongo_uri == "mongodb://m/"
    with pytest.raises(ValueError):
        Settings.from_env({"DAGONSERVICE_DUPLICATE_POLICY": "merge"})
