# mayan-comdirect
This is an add-on for the Mayan EDMS document management system.
It adds metadata to your invoices based on acutal payment data retrieved from your Comdirect bank account. 

Credits go to m42e and the great mayan-automatic-metadata addon from which I used the mayan API implementation and the architectural blueprint.

**!!! Important !!!** Please use this software at your own risk.
Incorrect usage may lead to an account lock.
Note that only P_TAN_PUSH TAN method is supported (set this as preferred TAN method in your account) since this is the only method that doesn't require us to send a challenge response back to the server.

Unfortunately Comdirect does not yet support the triggering of transactions.
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
- Comdirect bank account with activated API access and P_TAN_PUSH TAN method set as default method.

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

Mayan Comdirect consists of three services:

### 1. mayan-comdirect-web

This service only triggers tasks for the worker.

**The following environment variables are relevant:**
- `REDIS_URL`: provide a proper redis url for the task queuing

**The following endpoints are available:**

#### `http://mayam-comdirect-web:8000/transaction/<document_id>?interactive=false`
This endpoint extracts metadata from the document and tries to obtain a corresponding transaction from your bank account.
If a corresponding transaction is found additional tags and metadata can be attached to the document.
Just drop a `POST` or `GET` request to the endpoint with the documentid attached (e.g. `http://mayan-comdirect-web:8000/transaction/345`).
This will enqueue the task for the worker.
The `interactive` parameter is optional and defaults to `false` meaning that no TAN will be requested from the user when the session TAN is not already active.
Only use `interactive=true` when you know that the account holder will be able to answer the TAN challenge in the mobile app in a given time.
Ideally only use this flag in workflow steps that are manually taken by the user. 
When set to `true` the process will request a new session TAN from the account holder, otherwise the processing will only take place when a session TAN was already activated.
Note that only the `P_TAN_PUSH` TAN method is supported so make sure that this is your default method before using this service.
Comdirect will lock your account if you request 5 TANs without completing the challenge in between.
You can reset the counter by logging into your web account and enter a TAN challenge there.

#### `http://mayam-comdirect-web:8000/postbox?interactive=false&ads=false&archived=false&read=false`
This endpoint will import your postbox messages to Mayan EDMS.
Just drop a `POST` or `GET` request to this endpoint to check for new messages to import.
By setting any of the optional parameters ads, archived or read to true you can also import advertisements, archived messages or messages that have already been read (by default none of these will be imported).
Note that messages will be imported as new documents to Mayan EDMS even if they have been imported before.
All messages imported will set their state to `read=true` on Comdirect side so you will never import duplicates when using `read=false` (default value).Comdirect provides PDF and text based messages in the postbox. While PDF files are imported unchanged, text messages will be converted to a new PDF file before the import. 

#### `http://mayam-comdirect-web:8000/keepalive`
The Comdirect API provides an access token that remains valid for 10 minutes without using it and will become invalid after that period.
In addition to that a refresh token with an expiry of 20 minutes is provided that can be used to refresh the access token if it has expired.
This endpoint will simply refresh an access token if required (access token is expired) when you call it within 20 minutes after the session TAN was activated.
The keepalive endpoint does not accept the `interactive` parameter since it will never create a new session but only keep an existing one alive.  
Note that it is not guaranteed that the access and refresh tokens will be valid for 10/20  minutes after you called this endpoint:
During the first 10 minutes after a session TAN was activated no action will be taken by this endpoint since the obtained access token is still valid.
Only after these 10 minutes a refresh of the access token will be triggered which will effectively lead to new access and refresh tokens with a new lifetime of 10 and respectively 20 minutes.
You may use the mayan-comdirect-keepalive service to trigger this endpoint every 9 minutes automatically.
If the session TAN is no longer active when calling this endpoint nothing will happen which allows you to start the keepalive service at any time.
As soon as there is an active session the keepalive daemon will keep the session active until it is stopped.

### 2. mayan-comdirect-worker

This service receives tasks queued by the web service.

**The following environment variables are relevant:**
- `REDIS_URL`: provide a proper redis url for the task queuing
- `REDIS_CACHE_URL`: provide a proper redis url for caching the state of the comdirect API in between endpoint calls
- `MAYAN_USER`: User to access Mayan EDMS
- `MAYAN_PASSWORD`: Password for MAYAN_USER
- `MAYAN_URL`: URL of the Mayan EDMS instance. Should be `http://app:8000/api/v4/` (Note that the trailing `/` is required) if on the same docker network with default service names and Mayan EDMS version v4.X.
- `COMDIRECT_CLIENT_ID`: Comdirect Client ID
- `COMDIRECT_CLIENT_SECRET`: Comdirect Client Secret
- `COMDIRECT_ZUGANGSNUMMER`: Comdirect Zugangsnummer (Access number)
- `COMDIRECT_PIN`: Comdirect PIN
- All `COMDIRECT_*` variables can also be read from files by appending `_FILE` to the variable name (e.g. `COMDIRECT_PIN_FILE`). This allows the use of docker secrets (https://docs.docker.com/engine/swarm/secrets/).
- To Do: OIDC Documentation

**!!! Important !!!** For simplicity I use pickle to store the API state between API calls which is not necessarily secure. Therefore please make sure that the redis instance behind the REDIS_CACHE_URL is safely configured as it may be used to inject arbitrary code otherwise.

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

## Configuration

Mayan Comdirect requires some basic configurations to work in any environment. To change configuration you should copy the `config/config.json` file to your host machine, make your changes and mount this file as `/app/config/config.json` in your worker container.

The config file has sections for the transaction and the postbox endpoints:

```
{
    "transaction": {
        "matching": {
            "invoice_amount" : {
                "metadatatype": "invoiceamount",
                "unsigned": true,
                "locale": "de_DE"
            },
            "invoice_date" : {
                "metadatatype": "receiptdate",
                "dateformat": "%Y-%m-%d"
            },
            "invoice_number": {
                "metadatatype": "invoicenumber"
            }
        },
        "mapping": {
            "valutaDate": "valutadate",
            "bookingDate": "bookingdate"
        },
        "tagging": {
            "success": [
                "Paid"
            ],
            "failure": [
                "Open"
            ]
        }
    },
    "postbox": {
        "documenttype": "Contractdata",
        "mapping": {
            "dateCreation": "creationdate"
        },
        "tagging": [
        ]
    }
}
```

The transaction endpoint requires three configurations:
1. The matching config is used to find matches between mayan documents and Comdirect transactions.
Currently three parameters are required to point Mayan Comdirect to the metadata that should be used for matching: `invoice_amount`, `invoice_date` and `invoice_number`.
* `invoice_amount` should point to a metadatatype that holds the payment amount of the transaction.
Set `"unsigned": true` if the data stored in this metadatatype does not have a leading `-` for outgoing payments.
Also change the locale to your needs if you use a `.` instead of `,` as a decimal separator.
Since all non number characters with the exception of decimal separators are ignored you don't have to worry about currency characters and the like.
However please note that the metadata values obviously must match your account currency (should always be EUR).
* `invoice_date` is not actually used to match a transaction but to stop the search for a transaction.
It is assumed that the payment did not take place before the date when the invoice arrived so this should be a good value here.
But you may use any other date that seems suitable for your purpose.
You can also specify the date format (see https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior for more details)
* `invoice_number` is a number or text that should be in the payment to match this invoice (invoice number or payment reference).
2. The mapping config defines which fields of the API should be extracted and mapped to which metadata types in mayan.
The key is always the field in the Comdirect API (you will find the documentation in your Comdirect account when logged in), the value is the name of the metadatatype in mayan.
Right now you can only specify mappings on the lowest level of the json response of the API.
3. The tagging config tells Mayan Comdirect which tags should be applied to the document in case of sucess (= transaction was found) or failure (= transaction not found).
You can also provide empty lists if no tags should be applied.

The postbox endpoint primarily needs to know which document type should be used for the import of new documents. In addition to that you can also specify which API results should be mapped to metadata types in mayan. The logic is the same as for the transaction endpoint so see descriptions above on how to configure the mapping part of the postbox config.
