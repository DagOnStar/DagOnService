from threading import Lock
from flask import Flask, request
from flask_api import status
from pymongo import MongoClient
import bson
from bson import ObjectId
from flask import jsonify
import json
from collections import namedtuple
from flask_socketio import SocketIO, emit, join_room, leave_room, \
    close_room, rooms, disconnect
from workflow import Workflow

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.debug = True
app.config['SECRET_KEY'] = 'secret!'
#app.run(port=5000,threaded=True)
socketio = SocketIO(app, async_mode=async_mode)
thread = None
thread_lock = Lock()

client = MongoClient(port=27017)
db = client.dagon
workflows = {}


def _json_object_hook(d): return namedtuple('X', d.keys())(*d.values())


def json2obj(data): return json.loads(data, object_hook=_json_object_hook)


@app.route('/create', methods=['POST'])
def regist():
    content = request.json
    workflow = Workflow(content['name'], content['tasks'])
    workflowDict = workflow.__dict__
    db.workflows.insert_one(workflowDict)
    return jsonify({"id": str(workflowDict["_id"])}), status.HTTP_201_CREATED


@app.route('/changestatus/<workflow_id>/<task>/<status_code>', methods=['PUT'])
def update(workflow_id, task, status_code):

    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]))
        wObj.updateTaskStatus(task, status_code)
        db.workflows.replace_one({"_id": workflow['_id']}, wObj.__dict__, True)  # update in the database
        return jsonify({"status": "ok"})
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError, e:
        print e
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError, e:
        return jsonify({"status": "error", "message": "Task with key %s does not exist" % task})



@app.route("/<workflow_id>/<task>")
def getTask(workflow_id, task):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]))
        task = wObj.getTask(task)
        return jsonify({"status": "ok", "task": task})
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError, e:
        return jsonify({"status": "error", "message": "Task with key %s does not exist" % task})


@app.route("/<workflow_id>")
def getWorkflow(workflow_id):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]))
        return jsonify(wObj)
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND


@app.route("/add_task/<workflow_id>", methods=['POST'])
def add_task(workflow_id):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]))
        task = request.json
        if task is None:
            return jsonify({"status": "error", "message": "Invalid task"}), status.HTTP_404_NOT_FOUND
        wObj.addTask(task)
        db.workflows.replace_one({"_id": workflow['_id']}, wObj.__dict__, True)  # update in the database
        return jsonify({"message": "ok"})
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError, e:
        print e
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND


@app.route("/update/<workflow_id>/<task>/<parameter>", methods=['PUT'])
def update_task(workflow_id, task, parameter):
    try:
        value = request.args.get('value')
        print value, parameter
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        w_obj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]))
        w_obj.updateTask(task, parameter, value)
        db.workflows.replace_one({"_id": workflow['_id']}, w_obj.__dict__, True)  # update in the database
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError, e:
        print e
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError, e:
        return jsonify({"status": "error", "message": e}), status.HTTP_404_NOT_FOUND
    return jsonify({"status": "ok"})

# to receive notifications from a task
@app.route('/subscribe/<subscriber_id>/<to_id>/<task>')
def suscribe(subscriber_id, to_id, task):
    try:
        workflowSubscriber = db.workflows.find_one({"_id": ObjectId(subscriber_id)})
        workflowTarget = db.workflows.find_one({"_id": ObjectId(to_id)})  # only to check if the workflow exists
        targetObj = Workflow(workflowTarget["name"], workflowTarget["tasks"], creation_at=workflowTarget["creation_at"],
                             id=str(workflowTarget["_id"]))
        targetObj.addSubscriber(str(workflowSubscriber["_id"]))
        print targetObj.__dict__
        print targetObj.id
        db.workflows.replace_one({"_id": workflowTarget['_id']}, targetObj.__dict__, True)  # update in the database
        # db.workflows.replace_one({"_id":targetObj.id}, targetObj.__dict__, True) #update in the database
        # workflowSubscriber
        return jsonify({"message": "ok"})
    except bson.errors.InvalidId, e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % subscriber_id}), status.HTTP_404_NOT_FOUND
    except TypeError, e:
        print e
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % subscriber_id}), status.HTTP_404_NOT_FOUND


@app.route('/list')
def list():
    cursor = db.workflows.find({})
    workflowsLst = []
    for workflow in cursor:
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]), subscribers=workflow['subscribers'])
        workflowsLst.append(wObj)
    return jsonify(workflowsLst)


@app.route('/check')
def check():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    socketio.run(app, debug=True)
