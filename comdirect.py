from datetime import datetime
from datetime import timedelta
from typing import Type
import json
import logging
import requests
import secrets
import time

_logger = logging.getLogger(__name__)

class ComdirectTransaction():

    def __init__(self, valuta_date, remittance_info, amount_in_eur) -> None:
        self.valuta_date = valuta_date
        self.remittance_info = remittance_info
        self.amount_in_eur = amount_in_eur


class ComdirectRequest():

    def process_response(self, comdirect, response):
        _logger.debug(response.text)
        return response

    def _process_token_refresh(self, comdirect, response):

        json = response.json()

        comdirect.access_token = json['access_token']
        comdirect.refresh_token = json['refresh_token']
        comdirect.access_token_expiry = datetime.now(
        ) + timedelta(seconds=(json['expires_in']))
        comdirect.refresh_token_expiry = datetime.now() + timedelta(seconds=((20 * 60) - 1))


class Comdirect:

    def __init__(self, client_id, client_secret, zugangsnummer, pin) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.zugangsnummer = zugangsnummer
        self.pin = pin
        self.access_token_expiry = datetime.now()
        self.refresh_token_expiry = datetime.now()

    def login(self):
        try:
            if self.access_token_expiry > datetime.now():
                _logger.debug("Access token is still valid")
                return

            if self.refresh_token_expiry > datetime.now():
                _logger.debug(
                    "Refresh token is still valid. Performing access token refresh")
                self.__perform_token_refresh()
                return

            _logger.debug("Tokens are no longer valid. Starting login flow")
            self.__perform_login_flow()
        except:
            _logger.error("Login failed. Invalidating tokens.")
            self.access_token_expiry = datetime.now()
            self.refresh_token_expiry = datetime.now()
            raise

    def get_transactions(self, earliest):
        if self.access_token_expiry <= datetime.now():
            raise Exception('Access token expired. Please log in again.')

        try:
            self.__perform_request(Request_4_1_1(
                self.access_token, self.session_id, self.request_id))

            transactions = []
            booking_date_latest_transaction = datetime.now()
            paging_first = 0

            while booking_date_latest_transaction >= earliest:
                response = self.__perform_request(Request_4_1_3(
                    self.access_token, self.session_id, self.request_id, self.account_UUID, paging_first))
                
                json = response.json()
                
                booking_date_latest_transaction = datetime.strptime(json['aggregated']['bookingDateLatestTransaction'], '%Y-%m-%d')
                
                txs = json['values']
                for tx in txs:
                    valuta_date = datetime.strptime(tx['valutaDate'], '%Y-%m-%d')
                    if valuta_date >= earliest:
                        remittance_info = tx['remittanceInfo']
                        amount_in_eur = tx['amount']['value']
                        transactions.append(ComdirectTransaction(valuta_date, remittance_info, amount_in_eur))

                if json['aggregated']['latestTransactionIncluded']:
                    break

                paging_first += len(transactions) - 1
            
            return transactions

        except:
            _logger.error(
                "Failed to retrieve account transactions. Invalidating tokens.")
            self.access_token_expiry = datetime.now()
            self.refresh_token_expiry = datetime.now()
            raise

    def __perform_token_refresh(self):
        self.__perform_request(Request_3_1_1(
            self.client_id, self.client_secret, self.refresh_token))

    def __perform_login_flow(self):
        self.__update_session_id()
        self.__update_request_id()

        self.session = requests.Session()

        self.__perform_request(Request_2_1(
            self.client_id, self.client_secret, self.zugangsnummer, self.pin))

        self.__perform_request(Request_2_2(
            self.access_token, self.session_id, self.request_id))

        self.__perform_request(Request_2_3(
            self.access_token, self.session_id, self.request_id, self.session_UUID))

        self.__wait_for_challenge()
        if self.challenge_status != 'AUTHENTICATED':
            raise Exception(
                'TAN challenge failed. Status was ' + self.challenge_status)

        self.__perform_request(Request_2_4(
            self.access_token, self.session_id, self.request_id, self.session_UUID, self.challenge_id))

        self.__perform_request(Request_2_5(
            self.client_id, self.client_secret, self.access_token))

    def __update_session_id(self):
        self.session_id = secrets.token_hex(15)

    def __update_request_id(self):
        self.request_id = str(secrets.randbits(34) % 1000000000).zfill(9)

    def __wait_for_challenge(self):
        self.challenge_status = 'PENDING'
        while self.challenge_status == 'PENDING':
            time.sleep(3)
            self.__perform_request(Request_Challenge_Status(
                self.access_token, self.session_id, self.request_id, self.challenge_status_endpoint))

    def __perform_request(self, request: Type[ComdirectRequest]):

        response = self.session.request(request.method, request.endpoint,
                                        headers=request.headers, data=request.payload)
        if response.status_code not in request.accepted_response_codes:
            raise Exception('Status code should be one of: ' + str(request.accepted_response_codes) +
                            ', but was ' + str(response.status_code) + '. Response: ' + response.text)

        return request.process_response(self, response)


# Naming of request classes follows the naming in the API documentation

class Request_2_1(ComdirectRequest):
    def __init__(self, client_id, client_secret, zugangsnummer, pin):
        self.method = 'POST'
        self.endpoint = "https://api.comdirect.de/oauth/token"
        self.payload = 'client_id=' + client_id + '&client_secret=' + client_secret + \
            '&grant_type=password&username=' + zugangsnummer + '&password=' + pin
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        super()._process_token_refresh(comdirect, response)

        return super().process_response(comdirect, response)


class Request_2_2(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id):
        self.method = 'GET'
        self.endpoint = 'https://api.comdirect.de/api/session/clients/user/v1/sessions'
        self.payload = {}
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        json = response.json()

        comdirect.session_UUID = json[0]['identifier']

        return super().process_response(comdirect, response)


class Request_2_3(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id, session_UUID):
        self.method = 'POST'
        self.endpoint = 'https://api.comdirect.de/api/session/clients/user/v1/sessions/' + \
            session_UUID + '/validate'
        self.payload = json.dumps({
            "identifier": session_UUID,
            "sessionTanActive": True,
            "activated2FA": True
        })
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json'
        }
        self.accepted_response_codes = {
            201
        }

    def process_response(self, comdirect, response):

        headers = response.headers

        if 'x-once-authentication-info' not in headers:
            raise Exception('No TAN Challenge received.')

        authInfo = json.loads(headers['x-once-authentication-info'])

        if 'typ' not in authInfo or 'id' not in authInfo:
            raise Exception('Invalid TAN Challenge received.')

        # Only P_TAN_PUSH type allows us to proceed without further user interaction
        if authInfo['typ'] != 'P_TAN_PUSH':
            raise Exception('Unsupported TAN type: ' + authInfo['typ'])

        comdirect.challenge_id = authInfo['id']
        comdirect.challenge_status_endpoint = authInfo['link']['href']

        return super().process_response(comdirect, response)

# Not documented in API
class Request_Challenge_Status(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id, challenge_status_endpoint):
        self.method = 'GET'
        self.endpoint = 'https://api.comdirect.de' + challenge_status_endpoint
        self.payload = {}
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        json = response.json()

        comdirect.challenge_status = json['status']

        return super().process_response(comdirect, response)


class Request_2_4(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id, session_UUID, challenge_id):
        self.method = 'PATCH'
        self.endpoint = 'https://api.comdirect.de/api/session/clients/user/v1/sessions/' + session_UUID
        self.payload = json.dumps({
            "identifier": session_UUID,
            "sessionTanActive": True,
            "activated2FA": True
        })
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json',
            'x-once-authentication-info': '{"id":"' + challenge_id + '"}',
            'x-once-authentication': '000000'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        json = response.json()

        if not json['sessionTanActive'] or not json['activated2FA']:
            raise Exception(
                'Session TAN or 2FA not active. Something went wrong.')

        comdirect.session_UUID = json['identifier']

        return super().process_response(comdirect, response)


class Request_2_5(ComdirectRequest):
    def __init__(self, client_id, client_secret, access_token):
        self.method = 'POST'
        self.endpoint = "https://api.comdirect.de/oauth/token"
        self.payload = 'client_id=' + client_id + '&client_secret=' + \
            client_secret + '&grant_type=cd_secondary&token=' + access_token
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        super()._process_token_refresh(comdirect, response)

        return super().process_response(comdirect, response)


class Request_3_1_1(ComdirectRequest):
    def __init__(self, client_id, client_secret, refresh_token):
        self.method = 'POST'
        self.endpoint = "https://api.comdirect.de/oauth/token"
        self.payload = 'client_id=' + client_id + '&client_secret=' + \
            client_secret + '&grant_type=refresh_token&refresh_token=' + refresh_token
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        super()._process_token_refresh(comdirect, response)

        return super().process_response(comdirect, response)


class Request_4_1_1(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id):
        self.method = 'GET'
        self.endpoint = "https://api.comdirect.de/api/banking/clients/user/v2/accounts/balances"
        self.payload = {}
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        json = response.json()

        # TODO: Normally the first account should be fine but there is 
        # still room for imprevement here. Maybe we could get all accounts
        # here and request transactions for all of them as well.
        comdirect.account_UUID = json['values'][0]['accountId']

        return super().process_response(comdirect, response)


class Request_4_1_3(ComdirectRequest):
    def __init__(self, access_token, session_id, request_id, account_UUID, paging_first):
        self.method = 'GET'
        self.endpoint = "https://api.comdirect.de/api/banking/v1/accounts/" + \
            account_UUID + "/transactions?paging-first=" + str(paging_first)
        self.payload = {}
        self.headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + access_token,
            'x-http-request-info': '{"clientRequestId":{"sessionId":"' + session_id + '","requestId":"' + request_id + '"}}',
            'Content-Type': 'application/json'
        }
        self.accepted_response_codes = {
            200
        }

    def process_response(self, comdirect, response):

        # TODO: Do stuff

        return super().process_response(comdirect, response)
