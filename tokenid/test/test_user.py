import time

from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from asyncbb.test.base import AsyncHandlerTest
from asyncbb.test.database import requires_database
from tokenbrowser.crypto import sign_payload
from tokenbrowser.utils import data_decoder

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"

TEST_ADDRESS_2 = "0x056db290f8ba3250ca64a45d16284d04bc000000"


class UserHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def fetch(self, url, **kwargs):
        return super(UserHandlerTest, self).fetch("/v1{}".format(url), **kwargs)

    @gen_test
    @requires_database
    async def test_create_user(self):

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)
        timestamp = json_decode(resp.body)['timestamp']

        body = {
            "payload": {
                "timestamp": timestamp
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['owner_address'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)

    @gen_test
    @requires_database
    async def test_create_user_with_username(self):

        username = "bobsmith"

        body = {
            "payload": {
                "timestamp": int(time.time()),
                "username": username,
                "custom": {
                    "name": "Bob Smith"
                }
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 200)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNotNone(row)

        self.assertNotEqual(row['custom'], 'null')

    @gen_test
    @requires_database
    async def test_username_uniqueness(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS_2)

        # make sure creating a second user with the same username fails
        body = {
            "payload": {
                "timestamp": int(time.time()),
                "username": username,
                "custom": {
                    "name": "Bob Smith"
                }
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_unchanged_username(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS)

        # make sure settings a username with the same eth address succeeds
        body = {
            "payload": {
                "timestamp": int(time.time()),
                "username": username,
                "custom": {
                    "name": "Bob Smith"
                }
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="PUT", body=body)

        self.assertEqual(resp.code, 200)

    @gen_test
    @requires_database
    async def test_address_uniqueness(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", 'bobby', TEST_ADDRESS)

        # make sure creating a second user with the same username fails
        body = {
            "payload": {
                "timestamp": int(time.time()),
                "username": username,
                "custom": {
                    "name": "Bob Smith"
                }
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_create_user_with_invalid_username(self):

        username = "bobsmith$$$@@#@!!!"

        body = {
            "payload": {
                "timestamp": time.time(),
                "username": username
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNone(row)

    @gen_test
    @requires_database
    async def test_fake_signature(self):

        body = {
            "payload": {
                "timestamp": time.time()
            },
            "address": TEST_ADDRESS,
            "signature": "this is not a real signature!"
        }

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_wrong_address(self):

        body = {
            "payload": {
                "timestamp": time.time()
            },
            "address": "{}00000".format(TEST_ADDRESS[:-5])
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_expired_timestamp(self):

        body = {
            "payload": {
                "timestamp": int(time.time() - 60)
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="POST", body=body)

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_get_user(self):

        username = "bobsmith"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address, custom) VALUES ($1, $2, $3)", username, TEST_ADDRESS, '{"name":"Bob"}')

        resp = await self.fetch("/user/{}".format(username), method="GET")

        self.assertEqual(resp.code, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['owner_address'], TEST_ADDRESS)
        self.assertEqual(body['username'], username)

        # test get user by address
        resp = await self.fetch("/user/{}".format(TEST_ADDRESS), method="GET")

        self.assertEqual(resp.code, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['owner_address'], TEST_ADDRESS)
        self.assertEqual(body['username'], username)

        self.assertEqual(body['custom'].get('name'), 'Bob')

    @gen_test
    @requires_database
    async def test_get_invalid_user(self):

        resp = await self.fetch("/user/{}".format("21414124134234"), method="GET")

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_get_invalid_address(self):

        resp = await self.fetch("/user/{}".format("0x21414124134234"), method="GET")

        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_get_missing_user(self):

        resp = await self.fetch("/user/{}".format("bobsmith"), method="GET")

        self.assertEqual(resp.code, 404)

    @gen_test
    @requires_database
    async def test_update_user(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS)

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)
        timestamp = json_decode(resp.body)['timestamp']

        body = {
            "payload": {
                "timestamp": timestamp,
                "custom": {
                    "testdata": "æ"
                }
            },
            "address": TEST_ADDRESS
        }

        body['signature'] = sign_payload(TEST_PRIVATE_KEY, body['payload'])

        resp = await self.fetch("/user", method="PUT", body=body)

        self.assertEqual(resp.code, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(json_decode(row['custom']), body['payload']['custom'])
