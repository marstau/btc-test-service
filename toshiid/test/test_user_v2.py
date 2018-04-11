import time
import regex
import urllib.parse

from tornado.escape import json_decode
from tornado.testing import gen_test

from toshiid.app import urls
from toshiid.handlers_v1 import generate_username
from toshi.analytics import encode_id
from toshi.test.moto_server import requires_moto, BotoTestMixin
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest
from toshi.request import sign_request
from toshi.ethereum.utils import data_decoder
from toshi.handlers import TIMESTAMP_EXPIRY

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x7f0294b53af29ded2b5fa04b6225a1bc334a41e6"


class UserHandlerV2Test(BotoTestMixin, AsyncHandlerTest):

    def get_urls(self):
        return urls

    @gen_test
    async def test_generate_username_length(self):
        for n in [0, 5]:
            id = generate_username(n).split('user')[1]
            self.assertEqual(len(id), n)

    @gen_test
    @requires_database
    @requires_moto
    async def test_create_user(self):

        resp = await self.fetch("/v1/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['toshi_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertFalse(row['is_bot'])

        self.assertIsNotNone(row['username'])

        self.assertIsNotNone(row['avatar'])
        self.assertIsNotNone(
            regex.match("\/[^\/]+\/public\/identicon\/{}\.png".format(TEST_PAYMENT_ADDRESS),
                        urllib.parse.urlparse(row['avatar']).path), row['avatar'])

        async with self.boto:
            objs = await self.boto.list_objects()
        self.assertIn('Contents', objs)
        self.assertEqual(len(objs['Contents']), 1)

        resp = await self.fetch(row['avatar'], method="GET")
        self.assertEqual(resp.code, 200, "Got unexpected {} for url: {}".format(resp.code, row['avatar']))

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

    @gen_test
    @requires_database
    @requires_moto
    async def test_create_app_user(self):

        resp = await self.fetch("/v1/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={"bot": True, 'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['toshi_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_bot'])

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

    @gen_test
    @requires_database
    async def test_create_app_user_bad_bot_value(self):

        resp = await self.fetch("/v1/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={"bot": "bob", 'payment_address': TEST_PAYMENT_ADDRESS})

        self.assertResponseCodeEqual(resp, 400)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNone(row)

    @gen_test
    @requires_database
    @requires_moto
    async def test_create_user_missing_payment_address(self):
        resp = await self.fetch("/v1/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST")

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)

        resp = await self.fetch("/v2/user/{}".format(TEST_ADDRESS))
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertIsNone(body['payment_address'])

    @gen_test
    @requires_database
    @requires_moto
    async def test_create_user_with_username(self):

        username = "bobsmith"

        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "name": "Bob Smith"
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNotNone(row)

        self.assertEqual(row['username'], username)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

    @gen_test
    @requires_database
    async def test_username_uniqueness(self):

        username = 'bobsmith'
        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", username, TEST_ADDRESS_2)

        # make sure creating a second user with the same username fails
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "name": "Bob Smith"
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400)

        # make sure capitalisation doesn't matter
        body = {
            "username": capitalised,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "name": "Bob Smith"
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_unchanged_username(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", username, TEST_ADDRESS)

        # make sure settings a username with the same eth address succeeds
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "name": "Bob Smith"
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

    @gen_test
    @requires_database
    async def test_address_uniqueness(self):

        username = 'bobsmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", 'bobby', TEST_ADDRESS)

        # make sure creating a second user with the same username fails
        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "name": "Bob Smith"
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_create_user_with_invalid_username(self):

        username = "bobsmith$$$@@#@!!!"

        body = {
            "username": username,
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

        async with self.pool.acquire() as con:

            row = await con.fetchrow("SELECT * FROM users WHERE username = $1", username)

        self.assertIsNone(row)

    @gen_test
    @requires_database
    async def test_fake_signature(self):

        resp = await self.fetch_signed("/v2/user", method="POST",
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

        resp = await self.fetch_signed("/v2/user", method="POST",
                                       timestamp=timestamp, address=address, signature=signature,
                                       body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_expired_timestamp(self):

        timestamp = int(time.time() - (TIMESTAMP_EXPIRY + 60))
        body = {"payment_address": TEST_PAYMENT_ADDRESS}

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST", timestamp=timestamp, body=body)

        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_get_user(self):

        username = "bobsmith"
        capitalised = "BobSmith"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name) VALUES ($1, $2, $3)", capitalised, TEST_ADDRESS, 'Bob')

        resp = await self.fetch("/v2/user/{}".format(username), method="GET")

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['toshi_id'], TEST_ADDRESS)
        self.assertEqual(body['username'], capitalised)

        # test get user by address
        resp = await self.fetch("/v2/user/{}".format(TEST_ADDRESS), method="GET")

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['toshi_id'], TEST_ADDRESS)
        self.assertEqual(body['username'], capitalised)

        self.assertEqual(body['name'], 'Bob')

        # test all expected values are present
        expected_data = {
            "toshi_id": "0x0000000000000000000000000000000000000001",
            "type": "user",
            "payment_address": "0x0000000000000000000000000000000000000002",
            "username": "testuser",
            "name": "Test User",
            "description": "Hello World",
            "location": "The World",
            "avatar": "https://toshi-services/avatar.png",
            "reputation_score": 4.1,
            "average_rating": 4.9,
            "review_count": 100,
            "public": True
        }

        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO users (toshi_id, payment_address, username, name, avatar, description, location, reputation_score, review_count, average_rating, is_public) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
                expected_data['toshi_id'], expected_data['payment_address'], expected_data['username'], expected_data['name'], expected_data['avatar'], expected_data['description'], expected_data['location'], expected_data['reputation_score'], expected_data['review_count'], expected_data['average_rating'], expected_data['public'])

        resp = await self.fetch("/v2/user/{}".format(expected_data['toshi_id']))
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)

        self.assertEqual(len(expected_data), len(body))
        for key, expected_value in expected_data.items():
            self.assertIn(key, body)
            self.assertEqual(body[key], expected_value)

    @gen_test
    @requires_database
    async def test_get_invalid_user(self):

        resp = await self.fetch("/v2/user/{}".format("21414124134234"), method="GET")

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_get_invalid_address(self):

        resp = await self.fetch("/v2/user/{}".format("0x21414124134234"), method="GET")

        self.assertResponseCodeEqual(resp, 400)

    @gen_test
    @requires_database
    async def test_get_missing_user(self):

        resp = await self.fetch("/v2/user/{}".format("bobsmith"), method="GET")

        self.assertResponseCodeEqual(resp, 404)

    @gen_test
    @requires_database
    async def test_update_user(self):

        username = 'bobsmith'
        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        for name in ["\u611B\u611B\u611B", "æø"]:
            body = {
                "name": name
            }

            resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

            self.assertResponseCodeEqual(resp, 200)

            async with self.pool.acquire() as con:
                row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

            self.assertIsNotNone(row)
            self.assertEqual(row['name'], body['name'])

    @gen_test
    @requires_database
    async def test_update_user_duplicate_username(self):

        username_a = 'userA'
        username_b = 'userB'
        username_b_lower = 'userb'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", username_a, TEST_ADDRESS)
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", username_b, TEST_ADDRESS_2)

        for new_username in [username_b, username_b_lower]:
            body = {
                "username": new_username
            }

            resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

            self.assertResponseCodeEqual(resp, 400)

            async with self.pool.acquire() as con:
                row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

            self.assertIsNotNone(row)
            self.assertEqual(row['username'], username_a)

    @gen_test
    @requires_database
    async def test_update_user_username_with_different_case(self):

        username_a = 'userA'
        username_b = 'UsErA'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", username_a, TEST_ADDRESS)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "username": username_b
        })

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['username'], username_b)

    @gen_test
    @requires_database
    async def test_update_user_single_values(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "description": "I am neat",
            "location": "Oslo",
            "avatar": "https://example.com/blah.png",
            "name": "JeffBot",
            "bot": True,
            "payment_address": TEST_PAYMENT_ADDRESS,
            "username": "jeffbot"
        }

        for key, val in body.items():
            resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                           body={key: val})

            self.assertResponseCodeEqual(resp, 200, "failed updating '{}: {}'".format(key, val))

            async with self.pool.acquire() as con:
                row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

            self.assertIsNotNone(row)
            if key == 'bot':
                key = 'is_bot'
            self.assertEqual(row[key], val)

        # make sure the final data looks the same as the body
        for key, val in body.items():
            if key == 'bot':
                key = 'is_bot'
            self.assertEqual(row[key], val)

    @gen_test
    @requires_database
    async def test_update_user_payment_address(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "payment_address": TEST_PAYMENT_ADDRESS
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['payment_address'], TEST_PAYMENT_ADDRESS)

    @gen_test
    @requires_database
    async def test_update_user_set_bot(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        body = {
            "bot": True
        }

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body=body)

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_bot'])

    @gen_test
    @requires_database
    async def test_set_public_profile(self):
        """check that setting a users profile to public works"""

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE is_public = $1", True)

        self.assertIsNone(row)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "public": True
        })

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE is_public = $1", True)

        self.assertIsNotNone(row)

    @gen_test
    @requires_database
    async def test_set_public_for_apps(self):
        """check that setting an app to public works"""

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, is_bot) VALUES ($1, $2, TRUE)", capitalised, TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE is_public = $1", True)

        self.assertIsNone(row)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "public": True
        })

        self.assertResponseCodeEqual(resp, 200, resp.body)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE is_public = $1", True)

        self.assertIsNotNone(row)


class AppHandlerTestWithForcedPublicV2(AsyncHandlerTest):

    def setUp(self):
        super().setUp(extraconf={'general': {'apps_public_by_default': True}})

    def get_urls(self):
        return urls

    @gen_test
    async def test_generate_username_length(self):
        for n in [0, 5]:
            id = generate_username(n).split('user')[1]
            self.assertEqual(len(id), n)

    @gen_test
    @requires_database
    @requires_moto
    async def test_create_bot_user(self):

        resp = await self.fetch("/v1/timestamp")
        self.assertEqual(resp.code, 200)

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'payment_address': TEST_PAYMENT_ADDRESS, 'bot': True})

        self.assertResponseCodeEqual(resp, 200)

        body = json_decode(resp.body)

        self.assertEqual(body['toshi_id'], TEST_ADDRESS)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_bot'])
        self.assertTrue(row['is_public'])

        self.assertIsNotNone(row['username'])

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'bot': False})

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertFalse(row['is_bot'])
        self.assertFalse(row['is_public'])

        resp = await self.fetch_signed("/v2/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'bot': True})

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertTrue(row['is_bot'])
        self.assertTrue(row['is_public'])
