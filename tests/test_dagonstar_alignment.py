"""End-to-end alignment with the DAGonStar runtime.

A real HTTP server (backed by mongomock) is started on a free port and the
unmodified DAGonStar 3.0 client registers and runs workflows against it. The
module is skipped when DAGonStar is not installed.
"""

import json
import os
import shutil
import tempfile
import threading

import pytest
from werkzeug.serving import make_server

from conftest import make_app

dagon = pytest.importorskip("dagon")
from dagon.api import API  # noqa: E402
from dagon.task import DagonTask, TaskType  # noqa: E402


@pytest.fixture
def live_service():
    app = make_app()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port, app
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def scratch():
    path = tempfile.mkdtemp(prefix="dagonservice-test-")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def config(route, scratch):
    return {
        "dagon_service": {"route": route, "use": "True"},
        "ftp_pub": {"ip": "localhost"},
        "batch": {"scratch_dir_base": scratch + os.sep, "remove_dir": "False", "threads": "2"},
    }


def test_dagonstar_registers_runs_and_reports(live_service, scratch):
    route, _app = live_service
    workflow = dagon.Workflow("ServiceAlignment", config=config(route, scratch))
    assert workflow.is_api_available
    producer = DagonTask(TaskType.BATCH, "Producer", "echo 42 > value.txt")
    consumer = DagonTask(TaskType.BATCH, "Consumer.1",
                         "cat workflow:///Producer/value.txt > copy.txt")
    side = DagonTask(TaskType.BATCH, "Side", "true")
    workflow.add_task(producer)
    workflow.add_task(consumer)
    workflow.add_task(side)
    side.add_dependency_to(producer)
    workflow.make_dependencies()
    workflow.run()

    api = API(route)
    workflow_id = api.get_workflow_by_name("ServiceAlignment")
    assert workflow_id == workflow.workflow_id
    for name in ("Producer", "Consumer.1", "Side"):
        task = api.get_task(workflow_id, name)["task"]
        assert task["status"] == "FINISHED", (name, task)
        assert task["working_dir"] and task["working_dir"].startswith(scratch)
        assert [entry["status"] for entry in task["history"]][-1] == "FINISHED"
    consumer_task = api.get_task(workflow_id, "Consumer.1")["task"]
    assert "Producer" in consumer_task["prevs"]

    import requests
    summary = requests.get(route + "/api/v1/workflows/" + workflow_id).json()
    assert summary["status"] == "FINISHED"
    graph = requests.get(route + "/api/v1/workflows/%s/graph" % workflow_id).json()
    assert any(edge["source"] == "Producer" and edge["target"] == "Consumer.1" for edge in graph["edges"])


def test_exported_document_loads_in_dagonstar(live_service, scratch):
    route, _app = live_service
    workflow = dagon.Workflow("ExportAlignment", config=config(route, scratch))
    workflow.add_task(DagonTask(TaskType.BATCH, "A", "echo a > a.txt"))
    workflow.add_task(DagonTask(TaskType.BATCH, "B", "cat workflow:///A/a.txt"))
    import requests
    document = requests.get(route + "/api/v1/workflows/%s/document" % workflow.workflow_id).json()
    path = os.path.join(scratch, "exported.json")
    with open(path, "w") as handle:
        json.dump(document, handle)
    offline = dict(config(route, scratch))
    offline["dagon_service"] = {"use": "False"}
    reloaded = dagon.Workflow("Reloaded", config=offline, jsonload=document)
    assert {task.name for task in reloaded.tasks} == {"A", "B"}
    assert reloaded.find_task_by_name(reloaded.name, "B").command == "cat workflow:///A/a.txt"


def test_failed_task_is_reported(live_service, scratch):
    route, _app = live_service
    workflow = dagon.Workflow("ServiceFailure", config=config(route, scratch))
    workflow.add_task(DagonTask(TaskType.BATCH, "Broken", "exit 3"))
    workflow.make_dependencies()
    try:
        workflow.run()
    except Exception:
        pass  # DAGonStar may raise after recording the failure
    api = API(route)
    task = api.get_task(workflow.workflow_id, "Broken")["task"]
    assert task["status"] == "FAILED"
    import requests
    assert requests.get(route + "/api/v1/workflows/" + workflow.workflow_id).json()["status"] == "FAILED"


def test_token_protected_service_with_token_capable_client(scratch):
    """DAGonStar clients newer than 3.0.0 send ``[dagon_service] token``."""
    import inspect

    if "token" not in inspect.signature(API.__init__).parameters:
        pytest.skip("this DAGonStar client cannot send a token (3.0.0 and earlier)")
    app = make_app(api_token="s3cret")
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        route = "http://127.0.0.1:%d" % server.server_port
        cfg = config(route, scratch)
        cfg["dagon_service"]["token"] = "s3cret"
        workflow = dagon.Workflow("Tokened", config=cfg)
        workflow.add_task(DagonTask(TaskType.BATCH, "A", "true"))
        workflow.make_dependencies()
        workflow.run()
        api = API(route, token="s3cret")
        assert api.get_task(workflow.workflow_id, "A")["task"]["status"] == "FINISHED"
        without = dict(cfg)
        without["dagon_service"] = {"route": route, "use": "True"}
        with pytest.raises(Exception):
            dagon.Workflow("Untokened", config=without)
    finally:
        server.shutdown()
        thread.join(timeout=5)
