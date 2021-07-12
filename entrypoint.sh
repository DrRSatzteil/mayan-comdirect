#!/bin/bash

if [ "$1" == "rq" ]; then
    echo "rq mode"
    rq worker comdirect -vvv --url $REDIS_URL
fi

if [ "$1" == "web" ]; then
    echo "web mode"
    gunicorn service:app --error-logfile - -b '0.0.0.0:8000'
fi

if [ "$1" == "keepalive" ]; then
    echo "keepalive mode"
    while true
    do
        sleep 540
        wget -qO- "$WEB_URL/keepalive" &> /dev/null
    done
fi