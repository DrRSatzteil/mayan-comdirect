from datetime import datetime
from logging.config import fileConfig
from typing import Type
import comdirect
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
    config["required_metadata"] = {
        "invoice_amount": os.getenv("META_INVOICE_AMOUNT", "invoice_amount"),
        "invoice_number": os.getenv("META_INVOICE_NUMBER", "invoice_number"),
        "invoice_date": os.getenv("META_INVOICE_DATE", "invoice_date")
    }
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
    m = get_mayan(args)
    c = get_comdirect(args)
    _logger.info("load document %s", document)
    process(m, c, document, args['required_metadata'])


def process(m, c, document, required_metadata):
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

    for meta_name in required_metadata.values():
        if meta_name not in doc_metadata:
            _logger.error("not all required metadata is present")
            return

    # TODO: Support different date formats
    c.login()
    # TODO: Get date from document
    transactions = c.get_transactions(datetime.strptime('2020-10-10', '%Y-%m-%d'))
    cache_api_state(c)

    _logger.debug('Received transactions: ' + str(transactions))

    # TODO: Search for matching transactions. Let's start with this:
    # 1. invoicenumber is within booking reference
    # 2. invoiceamount matches the transaction amount
    # 3. transaction date is after invoicedate (to reduce the amount of transaction we have to go through)


def cache_api_state(comdirect):
    pickled = pickle.dumps(comdirect)
    # We need to log in again after 20 minutes anyway so we might as well clear the cache after 20 minutes
    redis_conn.set('comdirect_cache', pickled, 1200)
