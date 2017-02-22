from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from asyncbb.test.database import requires_database
from tokenservices.test.base import AsyncHandlerTest

from tokenid.test.test_user import TEST_PRIVATE_KEY, TEST_ADDRESS, TEST_PAYMENT_ADDRESS, TEST_ADDRESS_2

class LoginHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_login_user(self):


        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address, custom) VALUES ($1, $2, 'null')", 'BobSmith', TEST_ADDRESS)
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", 'JaneDoe', TEST_ADDRESS_2)
            row1 = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_ADDRESS)
            row2 = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_ADDRESS_2)

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
        self.assertEqual(body['owner_address'], TEST_ADDRESS)

        # make sure tokens are single use
        resp = await self.fetch("/login/verify/{}".format(auth_token))
        self.assertResponseCodeEqual(resp, 404)
