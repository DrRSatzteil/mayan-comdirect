# mayan-comdirect
Addon for Mayan EDMS.
Augments your invoices with acutal payment data from your Comdirect bank account. 

Credits go to m42e and the great mayan-automatic-metadata addon from which I used the mayan API implementation and the architectural blueprint.

**!!! Important !!!** Please use this software at your own risk.
Incorrect usage may lead to an account lock.
Note that only P_TAN_PUSH TAN method is supported (set this as preferred TAN method in your account) since this is the only method that won't require additional user interaction.

Unfortunately Comdirect does not support the triggering of transactions.
As soon as this is possible I will implement this feature.

# About Mayan Comdirect

I was looking for ways to trigger invoice payments straight out of Mayan EDMS and to keep track of paid invoices.
While unfortunately the first is not possible (yet) the latter can be done at least when you are a customer at Comdirect since they provide an API for end users.

What Mayan Comdirect can do right now:

- Retrieve payment data from your bank account and add metadata and tags to your invoice documents in Mayan EDMS
- Retrieve Postbox documents from Comdirect and import them into Mayan EDMS

What Mayan Comdirect cannot do right now:

- Trigger transactions based on scanned invoice documents

## HowTo

Requirements:

- Running Mayan EDMS, accessible from the node you run this on, and vice versa (for the webhook)
- A user in mayan, which is allowed to access the documents and the documents parsed content as well as the OCR content.
If you need a list of all required access rights, please open an issue.

Recommended:

- mayan-automatic-metadata (https://github.com/m42e/mayan-automatic-metadata): Mayan Comdirect requires some document metadata to be able to find the corresponding transactions in your bank account.
Therefore it is recommended to use the mayan-mam addon to add the required metadata first and then use Mayan Comdirect to check for corresponding account transactions.

Ideally you add Mayan Comdirect to the same docker network as your Mayan EDMS instance as shown in the example below.

Add the contents of the docker-compose file to the one you are using for mayan already.

```
version: '3.3'

services:
  
  #Please read Readme before using the keepalive function
  mayan-comdirect-keepalive:
    container_name: mayan-comdirect-keepalive
    image: drrsatzteil/mayan-comdirect-web:latest
    networks:
      - bridge
    restart: unless-stopped
    volumes:
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    environment:
      WEB_URL: mayan-comdirect-web:8000

  mayan-comdirect-web:
    container_name: mayan-comdirect-web
    image: drrsatzteil/mayan-comdirect-web:latest
    networks:
      - bridge
    restart: unless-stopped
    volumes:
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    environment:
      REDIS_URL: redis://:${MAYAN_REDIS_PASSWORD:-mayanredispassword}@redis:6379/3
            
  mayan-comdirect-worker:
    container_name: mayan-comdirect-worker
    image: drrsatzteil/mayan-comdirect-worker:latest
    networks:
      - bridge
    restart: unless-stopped
    volumes:
      - /etc/timezone:/etc/timezone:ro
      - /etc/localtime:/etc/localtime:ro
    environment:
      REDIS_URL: redis://:${MAYAN_REDIS_PASSWORD:-mayanredispassword}@redis:6379/3
      REDIS_CACHE_URL: redis://:${MAYAN_REDIS_PASSWORD:-mayanredispassword}@redis:6379/4
      MAYAN_USER: ${MAYAN_MAM_USER}
      MAYAN_PASSWORD: ${MAYAN_MAM_PASS}
      MAYAN_URL: http://app:8000/api/v4/
      COMDIRECT_CLIENT_ID: ${COMDIRECT_CLIENT_ID}
      COMDIRECT_CLIENT_SECRET: ${COMDIRECT_CLIENT_SECRET}
      COMDIRECT_ZUGANGSNUMMER: ${COMDIRECT_ZUGANGSNUMMER}
      COMDIRECT_PIN: ${COMDIRECT_PIN}

```

If redis is configured correctly you don't have to worry about concurrency (concurrent requests will wait for the finishing of running requests) or the Comdirect limit of 10 transactions per second (transactions will be delayed in case the limit was reached).

There are three services:

### 1. mayan-comdirect-web

This service only triggers tasks for the worker.

**The following environment variables are relevant:**
- `REDIS_URL`: provide a proper redis url for the task queuing

**The following endpoints are available:**

#### `http://mayam-comdirect-web:8000/transaction/<document_id>?interactive=false`
This endpoint extracts metadata from the document and tries to obtain a corresponding transaction from your bank account.
If a corresponding transaction is found additional tags and metadata can be attached to the document.
Just drop a `POST` or `GET` request to the endpoint with the documentid attached (e.g. `http://mayan-comdirect-web:8000/345`).
This will enqueue the task for the worker.
The `interactive`parameter is optional and defaults to `false` meaning that no TAN will be requested from the user when the session TAN is not already active.
When set to `true` the process will request a new session TAN from the account holder, otherwise the processing will only take place when a session TAN was already activated.
Note that only the `P_TAN_PUSH` TAN method is supported so make sure that this is your default method before using this service.
Comdirect will lock your account if you request 5 TANs without completing the challenge in between.
You can reset the counter by logging into your web account and enter a TAN challenge there.

#### `http://mayam-comdirect-web:8000/postbox?interactive=false&ads=false&archived=false&read=false`
This endpoint will import your postbox messages to Mayan EDMS.
By setting any of the optional parameters ads, archived or read to true you can also import advertisements, archived messages or messages that have already been read (by default none of these will be imported).
Note that messages will be imported as new documents to Mayan EDMS even if they have been imported before.
All messages imported will set their state to `read=true` at Comdirect so you will never import duplicates when using `read=false` (default value).

#### `http://mayam-comdirect-web:8000/keepalive`
This endpoint will simply refresh an access token if required when you call it within 20 minutes after the session TAN was activated.
Note that this does not necessarily mean that the access and refresh tokens will be valid for 10/20 more minutes after you called this endpoint.
During the first 10 minutes after a session TAN was activated no action will be taken by Mayan Comdirect since the obtained access token is still valid.
After these 10 minutes a refresh of the access token will be triggered which will effectively lead to new access and refresh tokens with a lifetime of 10 and 20 minutes.
You may use the mayan-comdirect-keepalive service to trigger this endpoint every 9 minutes.
If the session TAN is no longer active when calling this endpoint nothing will happen.

### 2. mayan-comdirect-worker

This service receives tasks queued by the web service.

**The following environment variables are relevant:**
- `REDIS_URL`: provide a proper redis url for the task queuing
- `REDIS_CACHE_URL`: provide a proper redis url for caching the state of the comdirect API in between endpoint calls
- `MAYAN_USER`: User to access Mayan EDMS
- `MAYAN_PASSWORD`: Password for MAYAN_USER
- `MAYAN_URL`: URL of the Mayan EDMS instance. Should be `http://app:8000/api/v4/` if on the same docker network with default service names and Mayan EDMS version v4.X.
- `COMDIRECT_CLIENT_ID`: Comdirect Client ID
- `COMDIRECT_CLIENT_SECRET`: Comdirect Client Secret
- `COMDIRECT_ZUGANGSNUMMER`: Comdirect Zugangsnummer (Access number)
- `COMDIRECT_PIN`: Comdirect PIN

### 3. mayan-comdirect-keepalive

This service simply calls the keepalive endpoint of the web service every 9 minutes.

**The following environment variables are relevant:**
- `WEB_URL`: should be set to `mayan-comdirect-web:8000` unless not deployed as suggested

**!!! Important !!!**
If this service is used your session will remain active until you stop this container.
This means that once every 20 minutes your COMDIRECT_CLIENT_ID, COMDIRECT_CLIENT_SECRET and your current refresh token will be transmitted over the network.
As long as the session is held active any API requests can be performed without further account holder interaction.
Note that anyone with access to the access token could also use the trading API of Comdirect even though this is not implemented in this project. 
This may pose a security risk and should therefore be avoided unless necessary.

### TODO: Configuration
