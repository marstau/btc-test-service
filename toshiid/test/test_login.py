import asyncio
from tornado.escape import json_decode
from tornado.testing import gen_test
from tornado.httpclient import AsyncHTTPClient, HTTPError

from toshiid.app import urls
from toshi.test.database import requires_database
from toshi.test.redis import requires_redis
from toshi.test.base import AsyncHandlerTest
from toshiid.login import LoginManager

from toshiid.test.test_user import TEST_PRIVATE_KEY, TEST_ADDRESS, TEST_PAYMENT_ADDRESS, TEST_ADDRESS_2

class LoginHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    async def create_test_users(self):
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", 'BobSmith', TEST_ADDRESS)
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", 'JaneDoe', TEST_ADDRESS_2)
            await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)
            await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)

    @gen_test
    @requires_database
    @requires_redis
    async def test_login_user(self):

        await self.create_test_users()
        request_token = 'abcdefghij'

        # do login
        resp = await self.fetch_signed("/login/{}".format(request_token), signing_key=TEST_PRIVATE_KEY, method="GET")
        self.assertResponseCodeEqual(resp, 204)

        # get auth token
        resp = await self.fetch("/login/{}".format(request_token))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertTrue('auth_token' in body)
        auth_token = body['auth_token']

        # verify token
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(body['token_id'], TEST_ADDRESS)

        # make sure tokens are single use
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 404)

    @gen_test
    @requires_database
    @requires_redis
    async def test_login_user_reverse(self):
        await self.create_test_users()
        request_token = 'abcdefghij'

        # do in reverse order
        f = asyncio.ensure_future(self.fetch("/login/{}".format(request_token)))

        await asyncio.sleep(1)

        resp = await self.fetch_signed("/login/{}".format(request_token), signing_key=TEST_PRIVATE_KEY, method="GET")
        self.assertResponseCodeEqual(resp, 204)

        resp = await f
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertTrue('auth_token' in body)
        auth_token = body['auth_token']

        # verify token
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(body['token_id'], TEST_ADDRESS)

    @gen_test(timeout=500)
    @requires_database
    @requires_redis
    async def test_login_check_spam(self):
        """Makes sure spamming of connections that timeout quickly
        get closed and removed from the login manager correctly.
        """
        await self.create_test_users()
        request_token = 'abcdefg{}'

        fs = []
        LIMIT = 1000
        TIMEOUT = 2.0
        for i in range(0, LIMIT):
            c = AsyncHTTPClient(force_instance=True)
            f = asyncio.ensure_future(c.fetch(
                self.get_url("/login/{}".format(request_token.format(i))),
                request_timeout=60.0 if i == 0 or i == LIMIT - 1 else TIMEOUT))
            fs.append(f)
            if i % 100 == 0 or i == LIMIT - 1:
                await asyncio.sleep(0)

        resp = await self.fetch_signed("/login/{}".format(request_token.format(0)), signing_key=TEST_PRIVATE_KEY, method="GET")
        self.assertResponseCodeEqual(resp, 204)

        resp = await fs[0]
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertTrue('auth_token' in body)
        auth_token = body['auth_token']

        # verify token
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(body['token_id'], TEST_ADDRESS)

        resp = await self.fetch_signed("/login/{}".format(request_token.format(LIMIT - 1)), signing_key=TEST_PRIVATE_KEY, method="GET")
        self.assertResponseCodeEqual(resp, 204)

        resp = await fs[-1]
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertTrue('auth_token' in body)
        auth_token = body['auth_token']

        # verify token
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(body['token_id'], TEST_ADDRESS)

        await asyncio.sleep(TIMEOUT)

        for f in fs[1:-1]:
            if not f.done():
                f.cancel()
            try:
                f.result()
            except:
                pass

        keys = len(LoginManager._instance._keys)
        while keys != 0:
            await asyncio.sleep((keys // 500) + 1)
            keys_ = len(LoginManager._instance._keys)
            if keys_ >= keys:
                self.fail("Login manager not reducing keys")
            keys = keys_

        self.assertEqual(len(LoginManager._instance._keys), 0)
