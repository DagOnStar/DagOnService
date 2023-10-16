from socketIO_client import SocketIO, LoggingNamespace
from os import getenv

class api_centinel:
    def __init__(self):
        try:
            url = getenv('CENTINEL') #read url}
            self.socket =  SocketIO(url,5000)
            self.status = self.CheckStatusSocket()
            self.socket._close()
        except Exception as e:
            print ("UH oh! something went wrong")
            self.status=False


    def UpdateTaskStatus(self,workflow,workflow_id ,task,status):
        if self.status:
            message = str(workflow)+","+str(workflow_id) +","+ str(task) +","+str(status)
            self.socket.emit('status',message)

    def UpdateWorkingDir(self,workflow,task,working_dir):
        if self.status:
            message = str(workflow)+","+str(task) +","+ str(working_dir)
            self.socket.emit('workingdir',message)
    
    def CheckStatusSocket(self):
        status = self.socket.emit('socketCheck',"status")
        if status == "True": return True
        else: return False