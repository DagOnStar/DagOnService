import mongomock
import pytest

from dagonservice import create_app
from dagonservice.config import Settings


def make_app(**overrides):
    settings = Settings(**overrides)
    database = mongomock.MongoClient()["dagon_test"]
    return create_app(settings, database=database)


@pytest.fixture
def app():
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()


def workflow_doc(name="Example", tasks=("A", "B")):
    """A document shaped like ``dagon.Workflow.as_json()`` in DAGonStar 3.0."""
    return {
        "name": name,
        "id": None,
        "host": "localhost",
        "tasks": {
            task: {"name": task, "status": "READY", "working_dir": None, "nexts": [], "prevs": [],
                   "command": "echo %s" % task, "type": "batch", "explicit_prevs": []}
            for task in tasks
        },
    }


def task_doc(name, command="true", type_="batch"):
    return {"name": name, "status": "READY", "working_dir": None, "nexts": [], "prevs": [],
            "command": command, "type": type_, "explicit_prevs": []}
