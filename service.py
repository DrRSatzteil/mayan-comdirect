from comdirectworker import import_postbox
from comdirectworker import keepalive
from comdirectworker import transaction
from flask import Flask
from flask import request
import os
import redis
import rq


redis_conn = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost'))
# no args implies the default queue
q = rq.Queue('comdirect', connection=redis_conn)

app = Flask('COMDIRECT')


@app.route('/')
def hello_world():
    return 'Nothing Here'


@app.route('/transaction/<int:document_id>', methods=['GET', 'POST'])
def trigger_transaction(document_id):
    interactive = request.args.get('interactive', default=False, type=bool)
    q.enqueue(transaction, str(document_id), interactive)
    return 'OK'


@app.route('/postbox', methods=['GET', 'POST'])
def trigger_postbox():
    interactive = request.args.get('interactive', default=False, type=bool)
    ads = request.args.get('ads', default=False, type=bool)
    archived = request.args.get('archived', default=False, type=bool)
    read = request.args.get('read', default=False, type=bool)
    q.enqueue(import_postbox, interactive, ads, archived, read)
    return 'OK'


@app.route('/keepalive', methods=['GET', 'POST'])
def trigger_keepalive():
    q.enqueue(keepalive)
    return 'OK'
