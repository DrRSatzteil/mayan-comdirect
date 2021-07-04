from datetime import datetime
from logging.config import fileConfig
from typing import Dict, Type
import comdirect
import json
import logging
import mayan
import os
import pickle
import redis


# read initial config file - make sure we don't squash any loggers
# not specifically declared in the config file.
fileConfig('/app/config/logging.ini', disable_existing_loggers=False)
_logger = logging.getLogger(__name__)

redis_conn = redis.from_url(os.getenv('REDIS_CACHE_URL', 'redis://localhost'))


def get_options():
    _logger.info("performing initial configuration")
    config = {}
    config["username"] = os.getenv("MAYAN_USER")
    config["password"] = os.getenv("MAYAN_PASSWORD")
    config["url"] = os.getenv("MAYAN_URL")
    config["client_id"] = os.getenv("COMDIRECT_CLIENT_ID")
    config["client_secret"] = os.getenv("COMDIRECT_CLIENT_SECRET")
    config["zugangsnummer"] = os.getenv("COMDIRECT_ZUGANGSNUMMER")
    config["pin"] = os.getenv("COMDIRECT_PIN")
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


def single(document):
    args = get_options()
    f = open('/app/config/metadatamapping.json',)
    metadatamapping = json.load(f)
    _logger.debug('Loaded metadatamapping: ' + str(metadatamapping))
    m = get_mayan(args)
    c = get_comdirect(args)
    _logger.info("load document %s", document)
    process(m, c, document, metadatamapping)


def process(m, c, document, metadatamapping):
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
    try:
        search_criteria['invoice_amount'] = doc_metadata[metadatamapping['invoice_amount']]['value']
        search_criteria['invoice_number'] = doc_metadata[metadatamapping['invoice_number']]['value']
        search_criteria['invoice_date'] = doc_metadata[metadatamapping['invoice_date']]['value']
    except:
        _logger.error('Not all required metadata was present')
        raise

    _logger.debug('Document metadata found: ' + str(search_criteria))

    # TODO: Support different date formats
    c.login()
    try:
        transactions = c.get_transactions(datetime.strptime(
            search_criteria['invoice_date'], '%Y-%m-%d'))
    except:
        _logger.error('Expected %Y-%m%d date format but received: ' +
                      search_criteria['invoice_date'])
        raise
    cache_api_state(c)

    for tx in transactions:
        try:
            tx_amount = tx['amount']['value']
            tx_remittanceInfo = tx['remittanceInfo']
            # TODO: Be more flexible regarding currency and metadata formatting...
            if(tx_amount.replace('-', '') == search_criteria['invoice_amount'].replace('€', '').replace(',', '.') and search_criteria['invoice_number'] in tx_remittanceInfo):
                _logger.info('Found transaction for document ' + str(document))
                # TODO: Add transaction metadata to document
                break
        except:
            _logger.debug('No amount or remittanceInfo found. Skipping transaction.')


def cache_api_state(comdirect):
    pickled = pickle.dumps(comdirect)
    # We need to log in again after 20 minutes anyway so we might as well clear the cache after 20 minutes
    redis_conn.set('comdirect_cache', pickled, 1200)
