from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from asyncbb.test.base import AsyncHandlerTest
from asyncbb.test.database import requires_database

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
