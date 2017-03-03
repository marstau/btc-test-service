import os
from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from tokenservices.test.base import AsyncHandlerTest
from asyncbb.test.database import requires_database
from ethutils import data_encoder, private_key_to_address

from urllib.parse import quote_plus

from tokenid.test.test_user import TEST_PRIVATE_KEY, TEST_ADDRESS, TEST_PAYMENT_ADDRESS

class SearchUserHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def fetch(self, url, **kwargs):
        return super(SearchUserHandlerTest, self).fetch(url, **kwargs)

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_username_query(self):

        username = "bobsmith"
        positive_query = 'obsm'
        negative_query = 'nancy'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", username, TEST_ADDRESS)

        resp = await self.fetch("/search/user?query={}".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 1)

        resp = await self.fetch("/search/user?query={}".format(negative_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

    @gen_test
    @requires_database
    async def test_invalid_username_query(self):

        username = "bobsmith"
        invalid_query = quote_plus('!@#$')

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", username, TEST_ADDRESS)

        resp = await self.fetch("/search/user?query={}".format(invalid_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

    @gen_test
    @requires_database
    async def test_username_query_sql_inject_attampt(self):

        username = "bobsmith"
        inject_attempt = quote_plus("x'; delete from users; select * from users")

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", username, TEST_ADDRESS)

        resp = await self.fetch("/search/user?query={}".format(inject_attempt), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT COUNT(*) AS count FROM users")

        self.assertEqual(row['count'], 1)

    @gen_test
    @requires_database
    async def test_bad_limit_and_offset(self):

        positive_query = 'obsm'

        resp = await self.fetch("/search/user?query={}&offset=x".format(positive_query), method="GET")
        self.assertEqual(resp.code, 400)

        resp = await self.fetch("/search/user?query={}&limit=x".format(positive_query), method="GET")
        self.assertEqual(resp.code, 400)

    @gen_test
    @requires_database
    async def test_limit_and_offset(self):

        username = "bobsmith"
        address = int(TEST_ADDRESS[2:], 16)
        num_of_users = 170

        async with self.pool.acquire() as con:
            # creates a bunch of users with numbering suffix to test limit and offset
            # insert users in reverse order to assure that search results are returned in alphabetical order
            for i in range(num_of_users - 1, -1, -1):
                await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)",
                                  # make sure the suffix is always the same length to ensure it's easy to match alphabetical ordering
                                  "{0}{1:0{2}}".format(username, i, len(str(num_of_users))),
                                  # makes sure every user has a different eth address
                                  "{0:#0{1}x}".format(address + i, 42))

        positive_query = 'obsm'
        test_limit = 30

        for i in range(0, num_of_users, test_limit):
            resp = await self.fetch("/search/user?query={}&limit={}&offset={}".format(positive_query, test_limit, i), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), min(i + test_limit, num_of_users) - i)
            j = i
            for res in body['results']:
                self.assertEqual(res['username'], "{0}{1:0{2}}".format(username, j, len(str(num_of_users))))
                j += 1

    @gen_test
    @requires_database
    async def test_search_for_user_with_no_custom(self):

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

        resp = await self.fetch("/search/user?query=Bob", method="GET")
        self.assertEqual(resp.code, 200)
        data = json_decode(resp.body)
        self.assertEqual(len(data['results']), 1)
        user = data['results'][0]
        self.assertTrue('custom' in user)
        self.assertIsNotNone(user['custom'])
        self.assertTrue('avatar' in user['custom'])
        self.assertIsNotNone(user['custom']['avatar'])

    @gen_test
    @requires_database
    async def test_only_apps_query(self):

        data_encoder, private_key_to_address
        users = [
            ('bob{}'.format(i), private_key_to_address(data_encoder(os.urandom(32))), False)
            for i in range(6)
        ]
        bots = [
            ('bot{}'.format(i), private_key_to_address(data_encoder(os.urandom(32))), True)
            for i in range(4)
        ]

        async with self.pool.acquire() as con:
            for args in users + bots:
                await con.execute("INSERT INTO users (username, token_id, is_app) VALUES ($1, $2, $3)", *args)

        resp = await self.fetch("/search/user?query=bo", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 10)

        resp = await self.fetch("/search/user?query=bo&apps=false", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 6)

        resp = await self.fetch("/search/user?query=bo&apps=true", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 4)
