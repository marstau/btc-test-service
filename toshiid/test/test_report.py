from tornado.testing import gen_test

from toshiid.app import urls
from toshi.analytics import encode_id
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest
from toshi.ethereum.utils import data_decoder

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_ADDRESS_2 = "0x444433335555ffffaaaa222211119999ffff7777"
TEST_ADDRESS_3 = "0x7f0294b53af29ded2b5fa04b6225a1bc334a41e6"


class UserHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_report_user(self):

        resp = await self.fetch_signed("/report", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'toshi_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 204)

        # ensure we get two tracking events
        e1 = await self.next_tracking_event()
        e2 = await self.next_tracking_event()
        if e1[0] != encode_id(TEST_ADDRESS):
            e1, e2 = e2, e1
        self.assertEqual(e1[1], "Made report")
        self.assertEqual(e2[1], "Was reported")

        async with self.pool.acquire() as con:
            row = await con.fetch("SELECT * FROM reports WHERE reporter_toshi_id = $1", TEST_ADDRESS)

        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]['details'], None)

        resp = await self.fetch_signed("/report", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'toshi_id': TEST_ADDRESS_2})
        self.assertResponseCodeEqual(resp, 204)

        async with self.pool.acquire() as con:
            row = await con.fetch("SELECT * FROM reports WHERE reporter_toshi_id = $1", TEST_ADDRESS)

        self.assertEqual(len(row), 2)

        resp = await self.fetch_signed("/report", signing_key=TEST_PRIVATE_KEY, method="POST",
                                       body={'toshi_id': TEST_ADDRESS_3, 'details': ''})
        self.assertResponseCodeEqual(resp, 204)

        async with self.pool.acquire() as con:
            row = await con.fetch("SELECT * FROM reports WHERE reportee_toshi_id = $1", TEST_ADDRESS_3)

        self.assertEqual(len(row), 1)
        self.assertEqual(row[0]['details'], '')
