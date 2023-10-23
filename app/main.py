from threading import Lock
from flask import Flask, request
from flask_api import status
from pymongo import MongoClient
import bson
from bson import ObjectId
from flask import jsonify
import json
from collections import namedtuple
from workflow import Workflow
import os
from centinel_api import api_centinel as api
import logging #logger

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.debug = True

MONGO_DB = os.environ['MONGO_DB']
#MONGO_DB = "localhost"
client = MongoClient(MONGO_DB,port=27017)
db = client.dagon
workflows = {}
centinel = api()
logging.basicConfig()
LOG = logging.getLogger('logger')

def _json_object_hook(d): return namedtuple('X', d.keys())(*d.values())


def json2obj(data): return json.loads(data, object_hook=_json_object_hook)


@app.route('/create', methods=['POST'])
def regist():
    content = request.json
    workflow = db.workflows.find_one({"name": content['name']})
    if workflow is not None:
        if app.debug == True: #for debuging only, if the workflow already exist is deleated.
            deleteWF(workflow['_id'])
        else:
            return jsonify({"status": "error", "message": "Workflow with name %s already exists" % content['name']}), status.HTTP_409_CONFLICT
    workflow = Workflow(content['name'], content['tasks'],host=content["host"])
    workflowDict = workflow.__dict__
    db.workflows.insert_one(workflowDict)
    LOG.error(workflowDict)
    return jsonify({"id": str(workflowDict["_id"])}), status.HTTP_201_CREATED


@app.route('/changestatus/<workflow_id>/<task>/<status_code>', methods=['PUT'])
def update(workflow_id, task, status_code):

    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        #wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        #id=str(workflow["_id"]),host=workflow["host"] )
        #wObj.updateTaskStatus(task, status_code)
        #db.workflows.replace_one({"_id": workflow['_id']}, wObj.__dict__, True)  # update in the database
        
        LOG.warning("CENTINEL STATUS: %s" % centinel.status)
        #TPS CENTINEL
        #centinel.UpdateTaskStatus(workflow["name"],workflow["_id"],task,status_code)
        db.workflows.update({"_id": workflow['_id']},{'$set':{"tasks."+task+".status" : status_code}}, True)

        return jsonify({"status": "ok"})
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError as e:
        print (e)
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError as e:
        return jsonify({"status": "error", "message": "Task with key %s does not exist" % task})

@app.route("/getworkflow/<workflow_name>", methods=['GET'])
def getWorkflowByName(workflow_name):
    try:
        workflow = db.workflows.find_one({"name": workflow_name})
        return str(workflow["_id"])
    except bson.errors.InvalidId:
        return jsonify({"status": "error", "message": "Invalid name %s" % workflow_name}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_name}), status.HTTP_404_NOT_FOUND

@app.route("/<workflow_id>/<task>",methods=['GET'])
def getTask(workflow_id, task):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]),host=workflow["host"] )
        task = wObj.getTask(task)
        return jsonify({"status": "ok", "task": task,"host": workflow["host"] })
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError as e:
        return jsonify({"status": "error", "message": "Task with key %s does not exist" % task})


@app.route("/<workflow_id>")
def getWorkflow(workflow_id):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]),host=workflow["host"])
        return jsonify(wObj)
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND


@app.route("/add_task/<workflow_id>", methods=['POST'])
def add_task(workflow_id):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]),host=workflow["host"])
        task = request.json
        if task is None:
            return jsonify({"status": "error", "message": "Invalid task"}), status.HTTP_404_NOT_FOUND
        wObj.addTask(task)
        db.workflows.replace_one({"_id": workflow['_id']}, wObj.__dict__, True)  # update in the database
        return jsonify({"message": "ok"})
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError as e:
        print(e)
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND


@app.route("/update/<workflow_id>/<task>/<parameter>", methods=['PUT'])
def update_task(workflow_id, task, parameter):
    try:
        value = request.args.get('value')
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})

        db.workflows.update({"_id": workflow['_id']},{'$set':{"tasks."+task+"."+parameter : value}}, True)

        if parameter == 'working_dir':
            centinel.UpdateWorkingDir(workflow['name'],task,value )


    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError as e:
        print(e)
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError as e:
        return jsonify({"status": "error", "message": e}), status.HTTP_404_NOT_FOUND
    return jsonify({"status": "ok"})


@app.route("/<workflow_id>/<task>/dependency/<dependency>", methods=['PUT'])
def add_dependency(workflow_id, task, dependency):
    try:
        workflow = db.workflows.find_one({"_id": ObjectId(workflow_id)})
        w_obj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]),host=workflow["host"])
        w_obj.addDependency(task, dependency)
        db.workflows.replace_one({"_id": workflow['_id']}, w_obj.__dict__, True)  # update in the database
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError as e:
        print(e)
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError as e:
        return jsonify({"status": "error", "message": e}), status.HTTP_404_NOT_FOUND
    return jsonify({"status": "ok"})

# to receive notifications from a task
@app.route('/subscribe/<subscriber_id>/<to_id>/<task>')
def suscribe(subscriber_id, to_id, task):
    try:
        workflowSubscriber = db.workflows.find_one({"_id": ObjectId(subscriber_id)})
        workflowTarget = db.workflows.find_one({"_id": ObjectId(to_id)})  # only to check if the workflow exists
        targetObj = Workflow(workflowTarget["name"], workflowTarget["tasks"], creation_at=workflowTarget["creation_at"],
                             id=str(workflowTarget["_id"]),host=workflowTarget["host"])
        targetObj.addSubscriber(str(workflowSubscriber["_id"]))
        db.workflows.replace_one({"_id": workflowTarget['_id']}, targetObj.__dict__, True)  # update in the database
        # db.workflows.replace_one({"_id":targetObj.id}, targetObj.__dict__, True) #update in the database
        # workflowSubscriber
        return jsonify({"message": "ok"})
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % subscriber_id}), status.HTTP_404_NOT_FOUND
    except TypeError as e:
        print(e)
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % subscriber_id}), status.HTTP_404_NOT_FOUND


@app.route('/list')
def list():
    cursor = db.workflows.find({})
    workflowsLst = []
    for workflow in cursor:
        wObj = Workflow(workflow["name"], workflow["tasks"], creation_at=workflow["creation_at"],
                        id=str(workflow["_id"]), subscribers=workflow['subscribers'],host=workflow["host"])
        workflowsLst.append(wObj)
    return jsonify(workflowsLst)


@app.route('/check')
def check():
    return jsonify({"status": "ok"})

@app.route("/delete/<workflow_id>")
def deleteWF(workflow_id):
    try:
        query ={"_id":ObjectId(workflow_id)}
        db.workflows.delete_one(query)
        return jsonify({"status": "ok"})
    except bson.errors.InvalidId as e:
        return jsonify({"status": "error", "message": "Invalid ID %s" % workflow_id}), status.HTTP_404_NOT_FOUND
    except TypeError:
        return jsonify(
            {"status": "error", "message": "Workflow %s does not exist" % workflow_id}), status.HTTP_404_NOT_FOUND
    except KeyError as e:
        return jsonify({"status": "error", "message": "Workflow with key %s does not exist" % workflow_id})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000,debug = True)
