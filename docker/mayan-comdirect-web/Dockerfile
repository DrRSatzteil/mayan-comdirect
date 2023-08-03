FROM python:3

COPY requirements.txt /
RUN python -m pip install -r /requirements.txt
WORKDIR /app
COPY . .
RUN mkdir logs

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["web"]
