
import datetime
import json

import make_serialization

class Workflow(object):

    def __init__(self, name, tasks, creation_at=None, id=None, subscribers=[],host = None):
        self.creation_at = creation_at if creation_at is not None else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.name = name
        self.tasks = tasks
        self.id = id
        self.subscribers = []
        self.host = host

    def updateTaskStatus(self, task, status):
        self.checkIfTaskExists(task)
        if not "history" in self.tasks[task]:
            self.tasks[task]['history'] = []
        self.tasks[task]['history'].append({"status":status, "datetime":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        self.tasks[task]["status"] = status

    def updateTask(self, task, parameter, value):
        self.checkIfTaskExists(task)
        if not parameter in self.tasks[task]:
            raise KeyError("Not parameter %s in task %s" % (task, parameter))
        self.tasks[task][parameter] = value

    def addDependency(self, task, dependency):
        self.checkIfTaskExists(task)
        if self.checkIfTaskExists(dependency) == False: #transversal point
            self.tasks[task]['prevs'].append(dependency)
        else:
            self.tasks[dependency]['nexts'].append(task)
            self.tasks[task]['prevs'].append(dependency)

    def checkIfTaskExists(self, task):
        if not task in self.tasks:
            return False
        else: return True
            #raise KeyError('Task %s does not exist'%task)

    def getLastTaskStatus(self, task):
        self.checkIfTaskExists(task)
        return {"status":self.tasks[task]["status"]}

    def addTask(self, task):
        self.tasks[task['name']] = task
        self.updateTaskStatus(task['name'], task['status'])
    
    def getTask(self, task):
        return self.tasks[task]

    def getName(self):
        return self.name

    def getTasks(self):
        return self.tasks
    
    def addSubscriber(self, workflow_id):
        self.subscribers.append(workflow_id)
        print(self.subscribers)

    def to_json(self):  # New special method.
        return self.__dict__


    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, 
            sort_keys=True, indent=4)