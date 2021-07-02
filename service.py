from flask import Flask
import os
import rq
import redis
from comdirectworker import single


redis_conn = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost'))
# no args implies the default queue
q = rq.Queue('comdirect', connection=redis_conn)

app = Flask('COMDIRECT')

@app.route('/')
def hello_world():
    return 'Nothing Here'


@app.route('/<int:document_id>', methods=['GET', 'POST'])
def trigger_comdirect(document_id):
    q.enqueue(single, str(document_id))
    return 'OK'
