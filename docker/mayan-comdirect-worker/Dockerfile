FROM python:3

RUN apt-get update && apt-get install -y \
  wkhtmltopdf \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /
RUN python -m pip install -r /requirements.txt
WORKDIR /app
COPY . .
RUN mkdir logs

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["rq"]
