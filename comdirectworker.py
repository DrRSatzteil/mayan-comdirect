from babel import numbers
from datetime import datetime
from logging.config import fileConfig
from typing import Dict, Type
import comdirect
import decimal
import json
import locale
import logging
import mayan
import os
import pickle
import re
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


def get_config():
    matching = json.load(open('/app/config/matching.json',))
    mapping = json.load(open('/app/config/mapping.json',))
    tagging = json.load(open('/app/config/tagging.json',))
    config = {
        "matching": matching,
        "mapping": mapping,
        "tagging": tagging
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
    config = get_config()
    m = get_mayan(args)
    c = get_comdirect(args)
    _logger.info("load document %s", document)
    process(m, c, document, config)


def process(m, c, document, config):
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
        amount = doc_metadata[config['matching']
                              ['invoice_amount']['metadatatype']]['value']
        unsigned = config['matching']['invoice_amount']['unsigned']
        amountlocale = config['matching']['invoice_amount']['locale']
        amount_filtered = ''.join(str(c) for c in (
            list(filter(lambda x: x in '-0123456789.,', amount))))
        amount_decimal = numbers.parse_decimal(
            amount_filtered, locale=amountlocale)
        search_criteria['invoice_amount'] = amount_decimal

        search_criteria['invoice_number'] = doc_metadata[config['matching']
                                                         ['invoice_number']['metadatatype']]['value']

        date = doc_metadata[config['matching']
                            ['invoice_date']['metadatatype']]['value']
        format = config['matching']['invoice_date']['dateformat']
        search_criteria['invoice_date'] = datetime.strptime(date, format)
    except:
        _logger.error('Matching configuration is incomplete or incorrect.')
        raise

    _logger.debug('Document metadata found: ' + str(search_criteria))

    c.login()
    transactions = c.get_transactions(search_criteria['invoice_date'])
    cache_api_state(c)

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
                _logger.info('Found transaction for document ' + str(document))
                metadata = {}
                # TODO: Add possibility to configure mappings on deeper levels
                # and basic transformations e.g. for date formats
                for property in config['mapping'].keys():
                    try:
                        propertyValue = tx[property]
                        metadata[config['mapping'][property]] = propertyValue
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
                                "metadata_type_pk": meta["metadata_type"]["id"],
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

                for t in config['tagging']['tags']:
                    if t not in m.tags:
                        _logger.info("Tag %s not defined in system", t)
                        continue
                    data = {"tag_pk": m.tags[t]["id"]}
                    result = m.post(
                        m.ep("tags", base=document["url"]), json_data=data)
                break
        except:
            _logger.debug(
                'No amount or remittanceInfo found. Skipping transaction.')
            raise


def cache_api_state(comdirect):
    pickled = pickle.dumps(comdirect)
    # We need to log in again after 20 minutes anyway
    # so we might as well clear the cache after 20 minutes
    redis_conn.set('comdirect_cache', pickled, 1200)
