import datetime
import os
import uuid

from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls

from tokenservices.test.database import requires_database
from tokenservices.test.base import AsyncHandlerTest
from tokenservices.ethereum.utils import data_decoder, private_key_to_address

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x7f0294b53af29ded2b5fa04b6225a1bc334a41e6"
TEST_PRIVATE_KEY_2 = data_decoder("0x223e2e480e0fd1c33ebacd929f7e0d6738d71104b552eeca3687d2ef33990a2d")

TEST_ADDRESS_3 = "0x38915AB51BCCE16B69663EC54B553ECA13524DAF"
TEST_PRIVATE_KEY_3 = data_decoder("0x2E206605C2DCB936835B753912A9B0EDAC3A3E9B1621B143D13A34FA25F018FC")

def random_private_key_and_address():
    key = os.urandom(32)
    address = private_key_to_address(key)
    return key, address

class UserMigrationTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_user_migrate(self):
        """test user migration"""

        username = 'jimmo'
        name = "James"
        name2 = "Jimmy"
        small_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        png_hash = '93ca32a536da1698ea979f183679af29'
        avatar_url = '/avatar/{}.png'.format(TEST_ADDRESS)
        avatar_url2 = '/avatar/{}.png'.format(TEST_ADDRESS_2)

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address, avatar) "
                              "VALUES ($1, $2, $3, $4, $5)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS, avatar_url)
            await con.execute("INSERT INTO avatars VALUES "
                              "($1, $2, $3, $4)",
                              TEST_ADDRESS, small_png, png_hash, 'PNG')

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="POST",
                                       body={'migration_key': migration_key,
                                             'payment_address': TEST_ADDRESS_2,
                                             'name': name2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        async with self.pool.acquire() as con:
            rowu1 = await con.fetchrow("SELECT COUNT(*) FROM users WHERE token_id = $1", TEST_ADDRESS)
            rowa1 = await con.fetchrow("SELECT COUNT(*) FROM avatars WHERE token_id = $1", TEST_ADDRESS)
            rowu2 = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS_2)
            rowa2 = await con.fetchrow("SELECT * FROM avatars WHERE token_id = $1", TEST_ADDRESS_2)
        self.assertEqual(rowu1['count'], 0)
        self.assertEqual(rowa1['count'], 0)
        self.assertIsNotNone(rowu2)
        self.assertIsNotNone(rowa2)
        self.assertEqual(rowu2['username'], username)
        self.assertEqual(rowu2['name'], name2)
        self.assertEqual(rowu2['payment_address'], TEST_ADDRESS_2)
        self.assertEqual(rowa2['hash'], png_hash)
        self.assertEqual(rowu2['avatar'], avatar_url2)

    @gen_test
    @requires_database
    async def test_user_migrate_different_account(self):
        """test user migration: make sure the migration key can't be used with a different address"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_3, method="POST",
                                       body={'migration_key': migration_key})
        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_user_migrate_exiting_account(self):
        """test user migration: make sure the migration key can't be used with a different address"""

        username = 'jimmo'
        name = "James"
        username2 = 'bobby'
        name2 = "Bob"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username2, TEST_ADDRESS_2, name2, TEST_ADDRESS_2)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_user_migrate_key_already_used(self):
        """test user migration: make sure the migration key can't be used again"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="POST",
                                       body={'migration_key': migration_key})
        self.assertResponseCodeEqual(resp, 200, resp.body)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="POST",
                                       body={'migration_key': migration_key, 'username': 'bob'})
        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_user_migrate_daily_limit(self):
        """test user migration: make sure only one migration can be done per day"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="POST",
                                       body={'migration_key': migration_key})
        self.assertResponseCodeEqual(resp, 200, resp.body)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="PUT",
                                       body={'token_id': TEST_ADDRESS_3})
        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_user_migrate_same_key_when_spammed(self):
        """test user migration: make sure we get the same key if spammed"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        for i in range(10):
            resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                           body={'token_id': TEST_ADDRESS_2})
            self.assertResponseCodeEqual(resp, 200, resp.body)
            self.assertEqual(json_decode(resp.body)['migration_key'], migration_key)

    @gen_test
    @requires_database
    async def test_user_migrate_remove_old_key_if_new_request(self):
        """test user migration: make sure any old requests are removed when
        a new one is made with a different address"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key_1 = json_decode(resp.body)['migration_key']

        # make sure rate limiter is hit first
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_3})
        self.assertResponseCodeEqual(resp, 429, resp.body)

        # update date so rate limiter will be avoided
        async with self.pool.acquire() as con:
            await con.execute("UPDATE migrations SET date = $1",
                              datetime.datetime.utcnow() - datetime.timedelta(minutes=1))

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_3})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key_2 = json_decode(resp.body)['migration_key']
        async with self.pool.acquire() as con:
            row1 = await con.fetchrow("SELECT * FROM migrations WHERE migration_key = $1",
                                      migration_key_1)
            row2 = await con.fetchrow("SELECT * FROM migrations WHERE migration_key = $1",
                                      migration_key_2)
        self.assertIsNone(row1)
        self.assertIsNotNone(row2)

    @gen_test
    @requires_database
    async def test_user_migrate_invalid_key_after_24_hours(self):
        """test user migration: make sure key is invalid after 1 day"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS, name, TEST_PAYMENT_ADDRESS)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body={'token_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 200, resp.body)
        migration_key = json_decode(resp.body)['migration_key']

        async with self.pool.acquire() as con:
            await con.execute("UPDATE migrations SET date = $1",
                              datetime.datetime.utcnow() - datetime.timedelta(hours=25))

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY_2, method="POST",
                                       body={'migration_key': migration_key})
        self.assertResponseCodeEqual(resp, 400, resp.body)

    @gen_test
    @requires_database
    async def test_get_chain_after_migrate(self):
        """test user migration: make sure key is invalid after 1 day"""

        username = 'jimmo'
        name = "James"

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, name, payment_address) "
                              "VALUES ($1, $2, $3, $4)",
                              username, TEST_ADDRESS_3, name, TEST_ADDRESS_3)
            await con.execute("INSERT INTO migrations VALUES ($1, $2, $3, true)",
                              uuid.uuid4().hex, TEST_ADDRESS_2, TEST_ADDRESS_3)
            await con.execute("INSERT INTO migrations VALUES ($1, $2, $3, true)",
                              uuid.uuid4().hex, TEST_ADDRESS, TEST_ADDRESS_2)

        # make sure migrated user is returned
        resp = await self.fetch("/user/{}".format(TEST_ADDRESS_2))
        self.assertResponseCodeEqual(resp, 200, resp.body)
        data = json_decode(resp.body)
        self.assertEqual(data['token_id'], TEST_ADDRESS_3)

        # make sure migrated user is returned from a chain of migrations
        resp = await self.fetch("/user/{}".format(TEST_ADDRESS))
        self.assertResponseCodeEqual(resp, 200, resp.body)
        data = json_decode(resp.body)
        self.assertEqual(data['token_id'], TEST_ADDRESS_3)
