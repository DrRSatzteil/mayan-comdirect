from logging.config import fileConfig
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
    process(m, c, document)


def process(m, c, document):
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

    required_metadata = (("invoiceamount", "invoicenumber", "receiptdate"))

    for meta_name in required_metadata:
        if meta_name not in doc_metadata:
            _logger.error("not all required metadata is present")
            return

    c.login()
    pickled = pickle.dumps(c)
    # We need to log in again after 20 minutes anyway so we might as well clear the cache then
    redis_conn.set('comdirect_cache', pickled, 1200)

    c.get_transactions()
