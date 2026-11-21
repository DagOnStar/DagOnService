# Getting started

This walkthrough starts the service with Docker Compose, registers a small
DAGonStar workflow, and follows its execution in the dashboard.

## 1. Start the service

```bash
git clone https://github.com/DagOnStar/DagOnService.git
cd DagOnService
docker compose up --build -d
curl http://localhost:57000/api/v1/health
```

The last command prints `{"status":"ok","version":"2.0.0","database":"ok"}`
once MongoDB is reachable. The dashboard is at <http://localhost:57000/>.

Without Docker, run a MongoDB server yourself and start the development server:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DAGONSERVICE_MONGO_URI=mongodb://localhost:27017 flask --app wsgi run --port 57000
```

## 2. Point DAGonStar at the service

Enable the service in the `dagon.ini` used by your workflow:

```ini
[dagon_service]
route = http://localhost:57000
use = True
```

or pass the same values programmatically through the `config` argument of
`dagon.Workflow`.

## 3. Run a workflow

```python
from dagon import Workflow
from dagon.task import DagonTask, TaskType

config = {
    "dagon_service": {"route": "http://localhost:57000", "use": "True"},
    "batch": {"scratch_dir_base": "/tmp/dagon/", "remove_dir": "False"},
}

workflow = Workflow("Hello-Service", config=config)
producer = DagonTask(TaskType.BATCH, "Produce", "echo 42 > answer.txt; sleep 2")
consumer = DagonTask(TaskType.BATCH, "Consume", "cat workflow:///Produce/answer.txt; sleep 2")
workflow.add_task(producer)
workflow.add_task(consumer)
workflow.make_dependencies()
workflow.run()
print("registered as", workflow.workflow_id)
```

While the program runs, open the dashboard: *Hello-Service* appears with status
`RUNNING`, its graph shows the `Produce → Consume` edge, and the event list
grows as each task moves through `WAITING`, `RUNNING` and `FINISHED`.

## 4. Query the record

```bash
curl http://localhost:57000/getworkflow/Hello-Service              # id, as plain text
curl http://localhost:57000/api/v1/workflows?name=Hello-Service    # summary
curl http://localhost:57000/api/v1/workflows/<id>                  # tasks and history
curl http://localhost:57000/api/v1/workflows/<id>/document         # DAGonStar JSON
```

The last document can be loaded back with `Workflow(..., jsonload=document)`
or imported into DAGonWeb.

## Next steps

- Read [DAGonStar integration](dagonstar_integration.md) to compose workflows
  through transversal references.
- Read [Deployment](deployment.md) and [Security](security.md) before exposing
  the service beyond a trusted network.
