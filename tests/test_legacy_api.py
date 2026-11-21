"""The routes called by ``dagon.api.API`` (DAGonStar 3.0) keep their contract."""

import threading

from conftest import make_app, task_doc, workflow_doc


def register(client, doc=None):
    response = client.post("/create", json=doc or workflow_doc())
    assert response.status_code == 201
    return response.get_json()["id"]


def test_check_supports_get_and_head(client):
    assert client.get("/check").get_json() == {"status": "ok"}
    assert client.head("/check").status_code == 200


def test_create_and_get(client):
    wid = register(client)
    body = client.get("/%s" % wid).get_json()
    assert body["id"] == wid
    assert body["name"] == "Example"
    assert set(body["tasks"]) == {"A", "B"}
    # Keys of the 2018 response are preserved.
    for key in ("creation_at", "name", "tasks", "id", "subscribers", "host"):
        assert key in body
    assert body["status"] == "READY"


def test_create_rejects_invalid_body(client):
    assert client.post("/create", data="nope", content_type="text/plain").status_code == 400
    assert client.post("/create", json={"tasks": {}}).status_code == 400
    assert client.post("/create", json={"name": "x", "tasks": {"A": {"name": "B"}}}).status_code == 400


def test_duplicate_policy_replace_is_default(client):
    first = register(client)
    second = register(client)
    assert first != second
    assert client.get("/%s" % first).status_code == 404
    assert client.get("/getworkflow/Example").get_data(as_text=True) == second


def test_duplicate_policy_reject():
    client = make_app(duplicate_policy="reject").test_client()
    register(client)
    assert client.post("/create", json=workflow_doc()).status_code == 409


def test_duplicate_policy_keep_returns_newest():
    client = make_app(duplicate_policy="keep").test_client()
    register(client)
    newest = register(client)
    assert client.get("/getworkflow/Example").get_data(as_text=True) == newest
    assert len(client.get("/list").get_json()) == 2


def test_change_status_records_history(client):
    wid = register(client)
    for status in ("WAITING", "RUNNING", "FINISHED"):
        assert client.put("/changestatus/%s/A/%s" % (wid, status)).status_code == 200
    task = client.get("/%s/A" % wid).get_json()["task"]
    assert task["status"] == "FINISHED"
    assert [item["status"] for item in task["history"]] == ["READY", "WAITING", "RUNNING", "FINISHED"]
    assert client.get("/%s" % wid).get_json()["status"] == "RUNNING"  # B is still READY


def test_change_status_errors(client):
    wid = register(client)
    assert client.put("/changestatus/%s/A/EXPLODED" % wid).status_code == 400
    assert client.put("/changestatus/%s/Z/RUNNING" % wid).status_code == 404
    assert client.put("/changestatus/not-an-id/A/RUNNING").status_code == 404
    assert client.put("/changestatus/%s/A/RUNNING" % ("0" * 24)).status_code == 404
    # The unknown task was not created as a side effect (the prototype upserted it).
    assert set(client.get("/%s" % wid).get_json()["tasks"]) == {"A", "B"}


def test_get_task_shape_used_for_transversal_references(client):
    wid = register(client)
    body = client.get("/%s/A" % wid).get_json()
    assert body["status"] == "ok"
    assert body["host"] == "localhost"
    for key in ("name", "type", "command", "working_dir", "status"):
        assert key in body["task"]
    assert client.get("/%s/missing" % wid).status_code == 404


def test_add_task(client):
    wid = register(client, workflow_doc(tasks=()))
    assert client.post("/add_task/%s" % wid, json=task_doc("C")).status_code == 201
    assert client.post("/add_task/%s" % wid, json=task_doc("C", "echo again")).status_code == 200
    assert client.get("/%s/C" % wid).get_json()["task"]["command"] == "echo again"
    assert client.post("/add_task/%s" % ("0" * 24), json=task_doc("C")).status_code == 404


def test_update_working_dir(client):
    wid = register(client)
    assert client.put("/update/%s/A/working_dir?value=/scratch/run/A" % wid).status_code == 200
    assert client.get("/%s/A" % wid).get_json()["task"]["working_dir"] == "/scratch/run/A"


def test_update_rejects_protected_and_malformed_attributes(client):
    wid = register(client)
    assert client.put("/update/%s/A/status?value=FINISHED" % wid).status_code == 400
    assert client.put("/update/%s/A/$where?value=1" % wid).status_code == 400
    assert client.put("/update/%s/A/a.b?value=1" % wid).status_code == 400
    assert client.put("/update/%s/A/working_dir" % wid).status_code == 400  # no value
    assert client.put("/update/%s/Z/working_dir?value=x" % wid).status_code == 404


def test_dependencies_are_idempotent_and_transversal_is_marked(client):
    wid = register(client)
    for _ in range(2):
        body = client.put("/%s/B/dependency/A" % wid).get_json()
        assert body == {"status": "ok", "transversal": False}
    tasks = client.get("/%s" % wid).get_json()["tasks"]
    assert tasks["B"]["prevs"] == ["A"]
    assert tasks["A"]["nexts"] == ["B"]
    assert client.put("/%s/B/dependency/Other" % wid).get_json()["transversal"] is True
    assert client.put("/%s/B/dependency/B" % wid).status_code == 400
    assert client.put("/%s/Z/dependency/A" % wid).status_code == 404


def test_subscribe_accumulates_subscribers(client):
    target = register(client, workflow_doc("T"))
    first = register(client, workflow_doc("S1"))
    second = register(client, workflow_doc("S2"))
    assert client.get("/subscribe/%s/%s/A" % (first, target)).status_code == 200
    assert client.get("/subscribe/%s/%s/A" % (second, target)).status_code == 200
    assert client.get("/subscribe/%s/%s/A" % (second, target)).status_code == 200
    assert client.get("/%s" % target).get_json()["subscribers"] == [first, second]


def test_delete(client):
    wid = register(client)
    assert client.get("/delete/%s" % wid).status_code == 200
    assert client.get("/delete/%s" % wid).status_code == 404
    assert client.get("/getworkflow/Example").status_code == 404


def test_task_names_with_dots_and_dollars(client):
    doc = workflow_doc(tasks=("step.1", "$cost", "50%"))
    wid = register(client, doc)
    assert client.put("/changestatus/%s/step.1/RUNNING" % wid).status_code == 200
    assert client.put("/%s/$cost/dependency/step.1" % wid).status_code == 200
    tasks = client.get("/%s" % wid).get_json()["tasks"]
    assert set(tasks) == {"step.1", "$cost", "50%"}
    assert tasks["step.1"]["status"] == "RUNNING"
    assert tasks["$cost"]["prevs"] == ["step.1"]
    assert tasks["step.1"]["nexts"] == ["$cost"]


def test_concurrent_status_updates_are_not_lost(client):
    names = ["T%d" % index for index in range(20)]
    wid = register(client, workflow_doc(tasks=names))
    app_client = client

    def worker(name):
        for status in ("WAITING", "RUNNING", "FINISHED"):
            app_client.put("/changestatus/%s/%s/%s" % (wid, name, status))

    threads = [threading.Thread(target=worker, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    body = client.get("/%s" % wid).get_json()
    assert body["status"] == "FINISHED"
    assert all(len(task["history"]) == 4 for task in body["tasks"].values())


def test_unknown_routes_return_json(client):
    response = client.get("/a/b/c/d")
    assert response.status_code == 404
    assert response.get_json()["status"] == "error"
