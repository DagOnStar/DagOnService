 
from threading import Lock
from flask import Flask, render_template, session, request
from flask import jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room, \
    close_room, rooms, disconnect

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode=async_mode)
thread = None
thread_lock = Lock()

worflows = {}

@app.route('/create', methods=['POST'])
def regist():
    content = request.json
    #return jsonify(worflows)

@app.route('/update')
def update(workflow, status):
    worflows[workflow] = status

@app.route('/suscribe')

@app.route('/list')
def list():
    return jsonify(worflows)

if __name__ == '__main__':
    socketio.run(app, debug=True)