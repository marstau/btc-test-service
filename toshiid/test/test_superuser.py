from tornado.testing import gen_test

from toshiid.app import urls
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest
from toshi.ethereum.utils import data_decoder

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x7f0294b53af29ded2b5fa04b6225a1bc334a41e6"


class SuperuserUpdateTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_superuser_update_user(self):

        # set superuser config
        self._app.config['superusers'] = {"{}".format(TEST_ADDRESS): 1}

        default_username = 'user12345'

        username = 'bobsmith'
        name = 'Bob Smith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username, TEST_ADDRESS_2)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username,
            "toshi_id": TEST_ADDRESS_2
        })

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)
            emptyrow = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNone(emptyrow)
        self.assertIsNotNone(row)
        self.assertEqual(row['name'], name)
        self.assertEqual(row['username'], username)

    @gen_test
    @requires_database
    async def test_superuser_update_user_2(self):

        # set superuser config
        self._app.config['superusers'] = {"{}".format(TEST_ADDRESS): 1}

        default_username = 'user12345'

        username = 'bobsmith'
        name = 'Bob Smith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username, TEST_ADDRESS_2)

        resp = await self.fetch_signed("/user/{}".format(TEST_ADDRESS_2), signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username,
        })

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)
            emptyrow = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNone(emptyrow)
        self.assertIsNotNone(row)
        self.assertEqual(row['name'], name)
        self.assertEqual(row['username'], username)

    @gen_test
    @requires_database
    async def test_non_superuser_update_should_fail(self):

        default_username1 = 'user12345'
        default_username2 = 'user23456'

        username = 'bobsmith'
        name = 'Bob Smith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username1, TEST_ADDRESS)
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username2, TEST_ADDRESS_2)

        # make sure things don't die when no superuser config is set
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username,
            "toshi_id": TEST_ADDRESS_2
        })

        self.assertResponseCodeEqual(resp, 401)

        async with self.pool.acquire() as con:
            row1 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)
            row2 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)

        self.assertIsNotNone(row1)
        self.assertIsNotNone(row2)
        self.assertEqual(row1['name'], None)
        self.assertEqual(row1['username'], default_username1)
        self.assertEqual(row2['name'], None)
        self.assertEqual(row2['username'], default_username2)

        # set superuser config to something not being user
        self._app.config['superusers'] = {"{}".format(TEST_PAYMENT_ADDRESS): 1}

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username,
            "toshi_id": TEST_ADDRESS_2
        })

        self.assertResponseCodeEqual(resp, 401)

        async with self.pool.acquire() as con:
            row1 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)
            row2 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)

        self.assertIsNotNone(row1)
        self.assertIsNotNone(row2)
        self.assertEqual(row1['name'], None)
        self.assertEqual(row1['username'], default_username1)
        self.assertEqual(row2['name'], None)
        self.assertEqual(row2['username'], default_username2)

        resp = await self.fetch_signed("/user/{}".format(TEST_ADDRESS_2), signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username
        })

        self.assertResponseCodeEqual(resp, 401)

        async with self.pool.acquire() as con:
            row1 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)
            row2 = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS_2)

        self.assertIsNotNone(row1)
        self.assertIsNotNone(row2)
        self.assertEqual(row1['name'], None)
        self.assertEqual(row1['username'], default_username1)
        self.assertEqual(row2['name'], None)
        self.assertEqual(row2['username'], default_username2)

    @gen_test
    @requires_database
    async def test_non_superuser_update_own_user_ok(self):

        # set superuser config
        self._app.config['superusers'] = {"{}".format(TEST_PAYMENT_ADDRESS): 1}

        default_username = 'user12345'

        username = 'bobsmith'
        name = 'Bob Smith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username, TEST_ADDRESS)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username,
            "toshi_id": TEST_ADDRESS
        })

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['name'], name)
        self.assertEqual(row['username'], username)

    @gen_test
    @requires_database
    async def test_non_superuser_update_own_user_ok_2(self):

        # set superuser config
        self._app.config['superusers'] = {"{}".format(TEST_PAYMENT_ADDRESS): 1}

        default_username = 'user12345'

        username = 'bobsmith'
        name = 'Bob Smith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", default_username, TEST_ADDRESS)

        resp = await self.fetch_signed("/user/{}".format(TEST_ADDRESS), signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "name": name,
            "username": username
        })

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(row)
        self.assertEqual(row['name'], name)
        self.assertEqual(row['username'], username)
