import asyncio
import os

from toshi.database import DatabaseMixin
from toshi.errors import JSONHTTPError
from datetime import datetime, timedelta
from toshi.ethereum.utils import data_encoder
from toshi.handlers import BaseHandler, RequestVerificationMixin
from toshiid.handlers import user_row_for_json
from toshi.redis import RedisMixin, get_redis_connection
from toshi.log import log

import string

LOGIN_KEY_PREFIX = "toshi:id:login:"
LOGIN_TOKEN_EXPIRY = 60
AUTH_TOKEN_REDIS_PREFIX = "toshi:auth_token:"
AUTH_TOKEN_EXIPRY = 60

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

class LoginManager:
    _instance = None

    def __init__(self):
        self._keys = []
        self._futures = {}
        self._running = False
        self._posted_warning = 0

    @staticmethod
    def create_login_check(key):
        if LoginManager._instance is None:
            LoginManager._instance = LoginManager()
        key = "{}{}".format(LOGIN_KEY_PREFIX, key)
        if key in LoginManager._instance._futures:
            return LoginManager._instance._futures[key]
        future = LoginManager._instance._futures[key] = asyncio.get_event_loop().create_future()
        LoginManager._instance._keys.append(key)
        future._time = asyncio.get_event_loop().time()
        LoginManager._instance._start()
        return future

    def _start(self):
        if self._running or len(self._keys) == 0:
            return
        self._running = True
        asyncio.get_event_loop().create_task(self._run())

    async def _run(self):
        while len(self._keys) > 0:
            try:
                # I'm worried here about attacks on the login endpoint that
                # would fill the keys list and block further login attempts
                # and/or use up all the memory on the server. This block
                # is in place to warn and debug issues should this end up
                # happening
                if len(self._keys) > 500:
                    grouping = len(self._keys) // 500
                    if grouping > self._posted_warning:
                        log.warning("Login keys list has reached {} keys".format(len(self._keys)))
                        self._posted_warning = grouping
                    elif grouping < self._posted_warning:
                        log.warning("Login keys list has returned to {} keys".format(len(self._keys)))
                        self._posted_warning = grouping
                elif self._posted_warning > 0:
                    log.warning("Login keys list length has returned to {} keys".format(len(self._keys)))
                    self._posted_warning = 0

                allkeys = self._keys[:]
                for offset in range(0, len(allkeys), 500):
                    keys = allkeys[offset:offset + 500]
                    if len(keys) == 0:
                        continue
                    # the timeout here will cause <1 second latency on new login
                    # requests.
                    result = await get_redis_connection().blpop(*keys, timeout=1, encoding='utf-8')
                    if result:
                        key, result = result
                        self._keys.remove(key)
                        keys.remove(key)
                        if key not in self._futures:
                            log.warning("got result for missing login key")
                        else:
                            future = self._futures.pop(key)
                            future.set_result(result)
                    # cleanup stale keys
                    for key in keys:
                        if key not in self._futures:
                            self._keys.remove(key)
                        future = self._futures[key]
                        if asyncio.get_event_loop().time() - future._time > LOGIN_TOKEN_EXPIRY:
                            future.set_excetion(TimeoutError())
                        if future.done():
                            del self._futures[key]
                            self._keys.remove(key)
            except:
                log.exception("error while checking logins")
                if len(self._keys) > 0:
                    await asyncio.sleep(1)
        self._running = False

class LoginHandler(RequestVerificationMixin, RedisMixin, DatabaseMixin, BaseHandler):

    def is_address_allowed(self, address):
        return True

    def set_login_result(self, key, address):
        pipe = self.redis.pipeline()
        key = "{}{}".format(LOGIN_KEY_PREFIX, key)
        pipe.lpush(key, address)
        pipe.expire(key, LOGIN_TOKEN_EXPIRY)
        return pipe.execute()

    def on_connection_close(self):
        super().on_connection_close()
        self._future.cancel()

    async def on_login(self, address):

        num = int(data_encoder(os.urandom(16))[2:], 16)
        token = b62encode(num)

        await self.redis.set('{}{}'.format(AUTH_TOKEN_REDIS_PREFIX, token), address,
                             expire=AUTH_TOKEN_EXIPRY)

        self.write({'auth_token': token})

    async def post(self, key):

        address = self.verify_request()
        await self.set_login_result(key, address)
        self.set_status(204)

    async def get(self, key):

        if self.is_request_signed():

            address = self.verify_request()
            await self.set_login_result(key, address)
            self.set_status(204)

        else:

            try:
                self._future = LoginManager.create_login_check(key)
                address = await self._future

                if address is None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'login_failed', 'message': 'Login failed'}]})
                if hasattr(self, 'on_login'):
                    f = self.on_login(address)
                    if asyncio.iscoroutine(f):
                        f = await f
                    return f
                # else
                self.write({"address": address})

            except TimeoutError:
                raise JSONHTTPError(408, body={'errors': [{'id': 'request_timeout', 'message': 'Login request timed out'}]})
            except asyncio.CancelledError:
                raise JSONHTTPError(400, body={'errors': [{'id': 'connection_closed', 'message': 'Login request connection closed'}]})

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'Content-Type')

    def options(self, address):
        self.set_status(204)
        self.finish()

class WhoDisHandler(DatabaseMixin, RedisMixin, BaseHandler):

    async def get(self, token):
        key = "{}{}".format(AUTH_TOKEN_REDIS_PREFIX, token)
        toshi_id = await self.redis.get(key, encoding='utf-8')
        if toshi_id is not None:
            await self.redis.delete(key)
            async with self.db:
                user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1",
                                              toshi_id)
            if user:
                self.write(user_row_for_json(self.request, user))
                return
        raise JSONHTTPError(404)
