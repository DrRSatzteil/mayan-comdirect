from babel import numbers
from datetime import datetime
from logging.config import fileConfig
from typing import Dict, Type
import comdirect
import io
import json
import logging
import mayan
import os
import pdfkit
import pickle
import redis
import redis_lock


# read initial config file - make sure we don't squash any loggers
# not specifically declared in the config file.
fileConfig('/app/config/logging.ini', disable_existing_loggers=False)
_logger = logging.getLogger(__name__)

redis_conn = redis.from_url(os.getenv('REDIS_CACHE_URL', 'redis://localhost'))


def get_mayan_options():
    _logger.info("initial mayan configuration")
    options = {}
    options["username"] = os.getenv("MAYAN_USER")
    options["password"] = os.getenv("MAYAN_PASSWORD")
    options["url"] = os.getenv("MAYAN_URL")
    return options

def get_comdirect_options():
    _logger.info("initial comdirect configuration")
    options = {}
    options["client_id"] = os.getenv("COMDIRECT_CLIENT_ID")
    options["client_secret"] = os.getenv("COMDIRECT_CLIENT_SECRET")
    options["zugangsnummer"] = os.getenv("COMDIRECT_ZUGANGSNUMMER")
    options["pin"] = os.getenv("COMDIRECT_PIN")
    return options

def get_config():
    config = json.load(open('/app/config/config.json',))
    return config


def get_mayan(args):
    _logger.info("logging into mayan")
    m = mayan.Mayan(args["url"])
    m.login(args["username"], args["password"])
    _logger.info("load meta informations")
    m.load()
    return m


def get_comdirect(args):
    cache = redis_conn.get('comdirect_cache')
    if cache == None:
        c = comdirect.Comdirect(
            args["client_id"], args["client_secret"], args["zugangsnummer"], args["pin"])
    else:
        c = pickle.loads(cache)
    return c


def transaction(document, interactive):
    args = get_mayan_options()
    config = get_config()
    m = get_mayan(args)
    _logger.info("load document %s", document)
    
    if isinstance(document, str):
        if document.isnumeric():
            document = m.get(m.ep(f"documents/{document}"))
        else:
            _logger.error("document value %s must be numeric", document)
            return

    if not isinstance(document, dict):
        _logger.error("could not retrieve document")
        return

    doc_metadata = {
        x["metadata_type"]["name"]: x
        for x in m.all(m.ep("metadata", base=document["url"]))
    }

    search_criteria = {}
    unsigned = True
    try:
        matchingconfig = config['transaction']['matching']
        amount = doc_metadata[matchingconfig['invoice_amount']['metadatatype']]['value']
        unsigned = matchingconfig['invoice_amount']['unsigned']
        amountlocale = matchingconfig['invoice_amount']['locale']
        amount_filtered = ''.join(str(c) for c in (
            list(filter(lambda x: x in '-0123456789.,', amount))))
        amount_decimal = numbers.parse_decimal(
            amount_filtered, locale=amountlocale)
        search_criteria['invoice_amount'] = amount_decimal

        search_criteria['invoice_number'] = doc_metadata[matchingconfig['invoice_number']['metadatatype']]['value']

        date = doc_metadata[matchingconfig['invoice_date']['metadatatype']]['value']
        format = matchingconfig['invoice_date']['dateformat']
        search_criteria['invoice_date'] = datetime.strptime(date, format)
    except:
        _logger.error('Matching configuration is incomplete or incorrect.')
        raise

    _logger.debug('Document metadata found: ' + str(search_criteria))

    # TODO: Cache transactions from the following call in redis and check if there are cached transactions available
    # before querying from comdirect. For simplicity we should only cache the results of the last request. Therefore
    # we always have to query comdirect again if the requested transaction was not found in the cache.

    with redis_lock.Lock(redis_conn, name='api_lock', expire=15, auto_renewal=True):
        c = get_comdirect(get_comdirect_options())
        transactions = c.get_transactions(
            search_criteria['invoice_date'], interactive)
        cache_api_state(c)

    transaction_found = False
    for tx in transactions:
        try:
            tx_amount = tx['amount']['value']
            tx_remittanceInfo = tx['remittanceInfo']

            if unsigned:
                tx_amount = tx_amount.replace('-', '')

            tx_amount_decimal = numbers.parse_decimal(
                tx_amount, locale='en_US')

            if(tx_amount_decimal == search_criteria['invoice_amount']
                    and search_criteria['invoice_number'] in tx_remittanceInfo):
                transaction_found = True
                _logger.info('Found transaction for document ' + str(document))
                metadata = {}
                # TODO: Add possibility to configure mappings on deeper levels
                # and basic transformations e.g. for date formats
                mappingconfig = config['transaction']['mapping']
                for property in mappingconfig.keys():
                    try:
                        propertyValue = tx[property]
                        metadata[mappingconfig[property]] = propertyValue
                    except:
                        _logger.error('Property ' + property +
                                      ' not found in transaction.')

                for meta in m.document_types[document["document_type"]["label"]]["metadatas"]:
                    meta_name = meta["metadata_type"]["name"]
                    if meta_name in metadata:
                        if meta_name not in doc_metadata:
                            _logger.info(
                                "Add metadata %s (value: %s) to %s",
                                meta_name,
                                metadata[meta_name],
                                document["url"],
                            )
                            data = {
                                "metadata_type_id": meta["metadata_type"]["id"],
                                "value": metadata[meta_name],
                            }
                            result = m.post(
                                m.ep("metadata", base=document["url"]), json_data=data
                            )
                        else:
                            data = {"value": metadata[meta_name]}
                            result = m.put(
                                m.ep(
                                    "metadata/{}".format(
                                        doc_metadata[meta_name]["id"]),
                                    base=document["url"],
                                ),
                                json_data=data,
                            )
                break
        except:
            _logger.debug(
                'No amount or remittanceInfo found. Skipping transaction.')
            raise
    
    taggingconfig = config['transaction']['tagging']
    if transaction_found:
        attach = taggingconfig['success']
    else:
        attach = taggingconfig['failure']
    for t in attach:
        if t not in m.tags:
            _logger.info("Tag %s not defined in system", t)
            continue
        data = {"tag": m.tags[t]["id"]}
        _logger.debug(
                'Trying to attach Tag ' + t + ' with tag id ' + data["tag"] + ' to document')
        result = m.post(
        m.ep("tags/attach", base=document["url"]), json_data=data)

def keepalive():
    with redis_lock.Lock(redis_conn, name='api_lock', expire=15, auto_renewal=True):
        c = get_comdirect(get_comdirect_options())
        c.login(False)
        cache_api_state(c)


def import_postbox(interactive, get_ads, get_archived, get_read):
    args = get_mayan_options()
    config = get_config()
    m = get_mayan(args)
    _logger.info("importing postbox")

    # TODO: The locking should all be centralized in get_comdirect
    with redis_lock.Lock(redis_conn, name='api_lock', expire=15, auto_renewal=True):
        c = get_comdirect(get_comdirect_options())
        documents = c.get_postbox_documents(
            interactive, get_ads, get_archived, get_read)
        cache_api_state(c)

    _logger.debug("Received %d documents", len(documents))
    postboxconfig = config['postbox']
    document_type_id = m.document_types[postboxconfig['documenttype']]['id']

    for document in documents:
        create_data = {'document_type_id': document_type_id,
                       'label': document['name'], 'language': 'deu'}
        result_create = m.post(
            m.ep("documents"), json_data=create_data
        )

        if document['mimeType'] == 'application/pdf':
            with io.BytesIO(document['content']) as documentfile:
                resultUpload = m.uploadfile(
                    m.ep(
                        "files",
                        base=result_create["url"],
                    ),
                    json_data={'action': 1},
                    file_data={'file_new': documentfile}
                )

        if document['mimeType'] == 'text/html':
            with io.StringIO(document['content']) as documentfile:
                pdf = pdfkit.from_file(documentfile, False)

            with io.BytesIO(pdf) as pdffile:
                resultUpload = m.uploadfile(
                    m.ep(
                        "files",
                        base=result_create["url"],
                    ),
                    json_data={'action': 1},
                    file_data={'file_new': pdffile}
                )
        
        metadata = {}
        # TODO: Add possibility to configure mappings on deeper levels
        # and basic transformations e.g. for date formats
        mappingconfig = config['postbox']['mapping']
        for property in mappingconfig.keys():
            try:
                propertyValue = document[property]
                metadata[mappingconfig[property]] = propertyValue
            except:
                _logger.error('Property ' + property +
                                ' not found in document.')

        for meta in m.document_types[result_create["document_type"]["label"]]["metadatas"]:
            meta_name = meta["metadata_type"]["name"]
            if meta_name in metadata:
                _logger.info(
                    "Add metadata %s (value: %s) to %s",
                    meta_name,
                    metadata[meta_name],
                    result_create["url"],
                )
                data = {
                    "metadata_type_id": meta["metadata_type"]["id"],
                    "value": metadata[meta_name],
                }
                result = m.post(
                    m.ep("metadata", base=result_create["url"]), json_data=data)


def cache_api_state(comdirect):
    # For simplicity we use pickle. For security reasons we should consider a JSON format.
    # However the datetime types in comdirect prevent the simple JSONification.
    pickled = pickle.dumps(comdirect)
    # We need to log in again after 20 minutes anyway
    # so we might as well clear the cache after 20 minutes
    redis_conn.set('comdirect_cache', pickled, 1200)
