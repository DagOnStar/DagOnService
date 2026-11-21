"""Documents written by the 2018 prototype are upgraded to schema version 2."""

import mongomock
from bson import ObjectId

from dagonservice import create_app
from dagonservice.config import Settings
from dagonservice.migrate import upgrade_all


def legacy_database():
    database = mongomock.MongoClient()["dagon"]
    database.workflows.insert_one({
        "_id": ObjectId("5bef0e1a2f8a4b0001a1b2c3"),
        "creation_at": "2018-11-16 16:03:05", "name": "Legacy", "id": None, "host": "10.0.0.1",
        "subscribers": ["abc", "abc"],
        "tasks": {
            "A": {"name": "A", "status": "FINISHED", "working_dir": "/tmp/A", "nexts": ["B"], "prevs": [],
                  "command": "echo", "type": "batch",
                  "history": [{"status": "RUNNING", "datetime": "2018-11-16 16:03:06"},
                              {"status": "FINISHED", "datetime": "2018-11-16 16:03:09"}]},
            "B": {"name": "B", "status": "bogus", "nexts": [], "prevs": ["A", "A"], "command": "cat",
                  "type": "batch"},
        },
    })
    return database


def test_upgrade_converts_and_is_idempotent():
    database = legacy_database()
    assert upgrade_all(database) == 1
    assert upgrade_all(database) == 0
    document = database.workflows.find_one()
    assert document["schema_version"] == 2 and "id" not in document
    assert document["subscribers"] == ["abc"]
    assert document["tasks"]["B"]["status"] == "READY"
    assert document["tasks"]["B"]["prevs"] == ["A"]
    assert [entry["status"] for entry in document["tasks"]["A"]["history"]] == ["RUNNING", "FINISHED"]


def test_upgraded_document_is_served_and_updatable():
    database = legacy_database()
    app = create_app(Settings(), database=database)
    result = app.test_cli_runner().invoke(args=["upgrade-documents"])
    assert "Upgraded 1 workflow document(s)" in result.output
    client = app.test_client()
    wid = "5bef0e1a2f8a4b0001a1b2c3"
    assert client.put("/changestatus/%s/B/RUNNING" % wid).status_code == 200
    body = client.get("/%s" % wid).get_json()
    assert body["created_at"].startswith("2018-11-16T16:03:05")
    assert body["status"] == "RUNNING"
    assert [entry["status"] for entry in body["tasks"]["B"]["history"]] == ["READY", "RUNNING"]
