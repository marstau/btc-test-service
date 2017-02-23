import time

from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from asyncbb.test.database import requires_database
from tokenservices.test.base import AsyncHandlerTest
from tokenbrowser.crypto import sign_payload
from tokenbrowser.request import sign_request
from ethutils import data_decoder

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
    @requires_database
    async def test_update_reputation(self):

        self._app.config['reputation'] = {'id': TEST_ADDRESS}

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (eth_address) VALUES ($1)", TEST_PAYMENT_ADDRESS)

        score = 4.4
        count = 10
        resp = await self.fetch_signed("/reputation", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'address': TEST_PAYMENT_ADDRESS, "score": score, "count": count})

        self.assertResponseCodeEqual(resp, 204)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_PAYMENT_ADDRESS)
        self.assertIsNotNone(row)
        self.assertEqual(float(row['reputation_score']), score)
        self.assertEqual(row['review_count'], count)

    @gen_test
    @requires_database
    async def test_cannot_update_when_sender_address_is_wrong(self):

        self._app.config['reputation'] = {'id': TEST_ADDRESS_2}

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (eth_address) VALUES ($1)", TEST_PAYMENT_ADDRESS)

        score = 4.4
        count = 10
        resp = await self.fetch_signed("/reputation", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'address': TEST_PAYMENT_ADDRESS, "score": score, "count": count})

        self.assertResponseCodeEqual(resp, 404)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_PAYMENT_ADDRESS)
        self.assertIsNotNone(row)
        self.assertIsNone(row['reputation_score'])
        self.assertEqual(row['review_count'], 0)

    @gen_test
    @requires_database
    async def test_cannot_update_when_no_address_in_config(self):

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (eth_address) VALUES ($1)", TEST_PAYMENT_ADDRESS)

        score = 4.4
        count = 10

        resp = await self.fetch_signed("/reputation", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'address': TEST_PAYMENT_ADDRESS, "score": score, "count": count})

        self.assertResponseCodeEqual(resp, 404)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM users WHERE eth_address = $1", TEST_PAYMENT_ADDRESS)
        self.assertIsNotNone(row)
        self.assertIsNone(row['reputation_score'])
        self.assertEqual(row['review_count'], 0)
