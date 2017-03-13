import time

from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from tokenid.handlers import generate_username
from asyncbb.test.database import requires_database
from tokenservices.test.base import AsyncHandlerTest
from tokenbrowser.crypto import sign_payload
from tokenbrowser.request import sign_request
from ethutils import data_decoder
from tokenservices.handlers import TIMESTAMP_EXPIRY

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x056db290f8ba3250ca64a45d16284d04bc000000"


class UserHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    async def test_generate_username_length(self):
        for n in [0,5]:
            id = generate_username(n).split('user')[1]
            self.assertEqual(len(id), n)

    @gen_test
    @requires_database
    async def test_create_user(self):

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['token_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertFalse(row['is_app'])

        self.assertIsNotNone(row['username'])

    @gen_test
    @requires_database
    async def test_create_app_user(self):

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={"is_app": True, 'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['token_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_app'])

    @gen_test
    @requires_database
    async def test_create_app_user_bad_is_app_value(self):

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={"is_app": "bob", 'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 400)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNone(row)

    @gen_test
    @requires_database
    async def test_create_user_missing_payment_address(self):
        # TODO: change this to make sure payment_address is required

        resp = await self.fetch("/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST")

        #self.assertResponseCodeEqual(resp, 400)
        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        #self.assertIsNone(row)
        self.assertIsNotNone(row)

    @gen_test
    @requires_database
    async def test_create_user_with_username(self):

        username = "bobsmith"

        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "custom": {
                "name": "Bob Smith"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNotNone(row)

        self.assertNotEqual(row['custom'], 'null')

    @gen_test
    @requires_database
    async def test_username_uniqueness(self):

        username = 'bobsmith'
        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", username, TEST_ADDRESS_2)

        # make sure creating a second user with the same username fails
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "custom": {
                "name": "Bob Smith"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400)

        # make sure capitalisation doesn't matter
        body = {
            "username": capitalised,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "custom": {
                "name": "Bob Smith"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400)


    @gen_test
    @requires_database
    async def test_unchanged_username(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", username, TEST_ADDRESS)

        # make sure settings a username with the same eth address succeeds
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "custom": {
                "name": "Bob Smith"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200)

    @gen_test
    @requires_database
    async def test_address_uniqueness(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", 'bobby', TEST_ADDRESS)

        # make sure creating a second user with the same username fails
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "custom": {
                "name": "Bob Smith"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_create_user_with_invalid_username(self):

        username = "bobsmith$$$@@#@!!!"

        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNone(row)

    @gen_test
    @requires_database
    async def test_fake_signature(self):

        resp = await self.fetch_signed("/user", method="POST",
                                signature="this is not a real signature!",
                                timestamp=int(time.time()),
                                address=TEST_ADDRESS)

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_wrong_address(self):

        timestamp = int(time.time())
        body = {"payment_address": TEST_PAYMENT_ADDRESS}
        signature = sign_request(TEST_PRIVATE_KEY, "POST", "/v1/user", timestamp, body)
        address = "{}00000".format(TEST_ADDRESS[:-5])

        resp = await self.fetch_signed("/user", method="POST",
                                timestamp=timestamp, address=address, signature=signature,
                                body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_expired_timestamp(self):

        timestamp = int(time.time() - (TIMESTAMP_EXPIRY + 60))
        body = {"payment_address": TEST_PAYMENT_ADDRESS}

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", timestamp=timestamp, body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_get_user(self):

        username = "bobsmith"
        capitalised = "BobSmith"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, custom) VALUES ($1, $2, $3)", capitalised, TEST_ADDRESS, '{"name":"Bob"}')

        resp = await self.fetch("/user/{}".format(username), method="GET")

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['token_id'], TEST_ADDRESS)
        self.assertEqual(body['username'], capitalised)

        # test get user by address
        resp = await self.fetch("/user/{}".format(TEST_ADDRESS), method="GET")

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['token_id'], TEST_ADDRESS)
        self.assertEqual(body['username'], capitalised)

        self.assertEqual(body['custom'].get('name'), 'Bob')

    @gen_test
    @requires_database
    async def test_get_invalid_user(self):

        resp = await self.fetch("/user/{}".format("21414124134234"), method="GET")

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_get_invalid_address(self):

        resp = await self.fetch("/user/{}".format("0x21414124134234"), method="GET")

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_get_missing_user(self):

        resp = await self.fetch("/user/{}".format("bobsmith"), method="GET")

        self.assertResponseCodeEqual(resp, 404)

    @gen_test
    @requires_database
    async def test_update_user(self):

        username = 'bobsmith'
        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "custom": {
                "testdata": "æø",
                "encodeddata": "\u611B\u611B\u611B"
            }
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(json_decode(row['custom']), body['custom'])

    @gen_test
    @requires_database
    async def test_update_user_payment_address(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['payment_address'], TEST_PAYMENT_ADDRESS)

    @gen_test
    @requires_database
    async def test_update_user_payment_address(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['payment_address'], TEST_PAYMENT_ADDRESS)


    @gen_test
    @requires_database
    async def test_update_user_set_is_app(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "is_app": True
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_app'])

    @gen_test
    @requires_database
    async def test_update_user_get_payment_address_from_custom(self):

        # for legacy

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "custom": {"payment_address": TEST_PAYMENT_ADDRESS}
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['payment_address'], TEST_PAYMENT_ADDRESS)
        self.assertIsNotNone(json_decode(row['custom']))

    @gen_test
    @requires_database
    async def test_default_avatar_for_new_user_with_no_custom(self):

        body = {
            "username": 'BobSmith',
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['token_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)
        self.assertIsNotNone(row['custom'])
        self.assertIsNotNone(json_decode(row['custom']))

        resp = await self.fetch("/user/BobSmith", method="GET")
        self.assertEqual(resp.code, 200)
        data = json_decode(resp.body)
        self.assertIsNotNone(data['custom'])
        self.assertTrue('avatar' in data['custom'])
        self.assertIsNotNone(data['custom']['avatar'])
        self.assertTrue(data['custom']['avatar'].startswith('http'))

    @gen_test
    @requires_database
    async def test_no_errors_with_null_custom(self):
        """Test for backwards compatibility with old users that had no default custom data"""

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, custom) VALUES ($1, $2, 'null')", 'BobSmith', TEST_ADDRESS)
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", 'JaneDoe', TEST_ADDRESS_2)
            row1 = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)
            row2 = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS_2)

        self.assertIsNotNone(row1['custom'])
        self.assertIsNone(json_decode(row1['custom']))
        self.assertIsNone(row2['custom'])

        resp = await self.fetch("/user/BobSmith", method="GET")
        self.assertEqual(resp.code, 200)
        data = json_decode(resp.body)
        self.assertIsNotNone(data['custom'])
        self.assertTrue('avatar' in data['custom'])
        self.assertIsNotNone(data['custom']['avatar'])

        resp = await self.fetch("/user/JaneDoe", method="GET")
        self.assertEqual(resp.code, 200)
        data = json_decode(resp.body)
        self.assertIsNotNone(data['custom'])
        self.assertTrue('avatar' in data['custom'])
        self.assertIsNotNone(data['custom']['avatar'])
