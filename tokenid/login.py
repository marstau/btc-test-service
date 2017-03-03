import asyncio
import os

from asyncbb.handlers import BaseHandler
from asyncbb.database import DatabaseMixin
from asyncbb.errors import JSONHTTPError
from datetime import datetime, timedelta
from ethutils import data_encoder
from functools import partial
from tokenservices.handlers import RequestVerificationMixin
from tornado.ioloop import IOLoop
from .handlers import user_row_for_json

import string

b62chars = string.digits + string.ascii_letters
b62base = len(b62chars)

def b62encode(num):
    '''Encode number in base62, returns a string.'''
    if num < 0:
        raise ValueError('cannot encode negative numbers')

    if num == 0:
        return b62chars[0]

    digits = []
    while num:
        rem = num % b62base
        num = num // b62base
        digits.append(b62chars[rem])
    return ''.join(reversed(digits))


def b62decode(string):
    '''Decode a base62 string to a number.'''
    loc = b62chars.index
    size = len(string)
    num = 0

    for i, ch in enumerate(string, 1):
        num += loc(ch) * (b62base ** (size - i))

    return num

DEFAULT_LOGIN_REQUESTS = {}

class LoginAttempt:

    def __init__(self, timeout=60, on_timeout=None):
        self._future = asyncio.Future()
        self._timeout = timeout
        if on_timeout:
            ioloop = IOLoop.current()
            self._looptimeout = ioloop.add_timeout(ioloop.time() + timeout, on_timeout)
        else:
            self._looptimeout = None

    def set_cancelled(self):
        if not self._future.done():
            self._future.set_result(None)

    def cancel_timeout(self):
        if self._looptimeout:
            IOLoop.current().remove_timeout(self._looptimeout)
            self._looptimeout = None

    def set_success(self, address):
        if not self._future.done():
            self._future.set_result(address)

    def set_failed(self, address):
        if not self._future.done():
            self._future.set_result(False)

    def __await__(self):
        return self._future.__await__()

class LoginHandler(RequestVerificationMixin, DatabaseMixin, BaseHandler):

    @property
    def login_requests(self):
        return DEFAULT_LOGIN_REQUESTS

    def is_address_allowed(self, address):
        return True

    def create_new_login_future(self, key, timeout=60):
        if key in self.login_requests:
            self.login_request[key].set_cancelled()
        self.login_requests[key] = LoginAttempt(on_timeout=partial(self.invalidate_login, key))

    def invalidate_login(self, key):
        if key in self.login_requests:
            self.login_requests[key].set_cancelled()
            self.login_requests[key].cancel_timeout()
        del self.login_requests[key]

    def set_login_result(self, key, address):
        if key not in self.login_requests:
            self.create_new_login_future(key)
        if self.is_address_allowed(address):
            self.login_requests[key].set_success(address)
        else:
            self.set_cancelled()

    async def on_login(self, address):

        num = int(data_encoder(os.urandom(16))[2:], 16)
        token = b62encode(num)

        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users where token_id = $1", address)
            if row is None:
                raise JSONHTTPError(401)
            await self.db.execute("INSERT INTO auth_tokens (token, address) VALUES ($1, $2)",
                                  token, address)
            await self.db.commit()
        self.write({'auth_token': token})

    async def post(self, key):

        address = self.verify_request()
        self.set_login_result(key, address)
        self.set_status(204)

    async def get(self, key):

        if self.is_request_signed():

            address = self.verify_request()
            self.set_login_result(key, address)
            self.set_status(204)

        else:

            if key not in self.login_requests:
                self.create_new_login_future(key)

            address = await self.login_requests[key]

            if address is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'request_timeout', 'message': 'Login request timed out'}]})
            if address is False:
                raise JSONHTTPError(401, body={'errors': [{'id': 'login_failed', 'message': 'Login failed'}]})

            if hasattr(self, 'on_login'):
                f = self.on_login(address)
                if asyncio.iscoroutine(f):
                    f = await f
                return f
            # else
            self.write({"address": address})

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'Content-Type')

    def options(self, address):
        self.set_status(204)
        self.finish()

class WhoDisHandler(DatabaseMixin, BaseHandler):

    async def get(self, token):

        user = None
        async with self.db:
            row = await self.db.fetchrow("SELECT u.*, a.created AS auth_token_created FROM auth_tokens a "
                                         "JOIN users u ON a.address = u.token_id "
                                         "WHERE a.token = $1", token)
            if row is not None:
                # only allow tokens to be used for 10 minutes
                print(row)
                if row['auth_token_created'] + timedelta(minutes=10) > datetime.utcnow():
                    user = user_row_for_json(row)
                else:
                    print('expired')
                # remove token after single use
                await self.db.execute("DELETE FROM auth_tokens WHERE token = $1", token)
                await self.db.commit()
            else:
                print('not found')

        if user:
            self.write(user)
        else:
            raise JSONHTTPError(404)
