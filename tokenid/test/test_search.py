from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from asyncbb.test.base import AsyncHandlerTest
from asyncbb.test.database import requires_database

from urllib.parse import quote_plus

TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"

class SearchUserHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def fetch(self, url, **kwargs):
        return super(SearchUserHandlerTest, self).fetch("/v1{}".format(url), **kwargs)

    @gen_test
    @requires_database
    async def test_username_query(self):

        username = "bobsmith"
        positive_query = 'obsm'
        negative_query = 'nancy'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS)

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
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS)

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
            await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, TEST_ADDRESS)

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
                await con.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)",
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
