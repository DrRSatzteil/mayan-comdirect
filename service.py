from flask import Flask
import os
import rq
import redis
from comdirectworker import keepalive
from comdirectworker import single
from comdirectworker import import_postbox


redis_conn = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost'))
# no args implies the default queue
q = rq.Queue('comdirect', connection=redis_conn)

app = Flask('COMDIRECT')

@app.route('/')
def hello_world():
    return 'Nothing Here'

@app.route('/tx/<int:document_id>', methods=['GET', 'POST'])
def trigger_tx(document_id):
    q.enqueue(single, str(document_id))
    return 'OK'

@app.route('/postbox', methods=['GET', 'POST'])
def trigger_postbox():
    q.enqueue(import_postbox)
    return 'OK'

@app.route('/keepalive', methods=['GET', 'POST'])
def trigger_keepalive():
    q.enqueue(keepalive)
    return 'OK'