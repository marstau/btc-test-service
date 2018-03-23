import asyncio
import os
import uuid

from datetime import datetime, timedelta

from tornado.escape import json_decode
from tornado.testing import gen_test

from toshiid.app import urls
from toshiid.housekeeping import HousekeepingApplication
from toshi.test.base import AsyncHandlerTest
from toshi.test.database import requires_database
from toshi.ethereum.utils import private_key_to_address

class HousekeepingTest(AsyncHandlerTest):

    def setUp(self):
        super().setUp(extraconf={'general': {'apps_dont_require_websocket': False}})

    def get_urls(self):
        return urls

    def fetch(self, url, **kwargs):
        return super().fetch("/v1{}".format(url), **kwargs)

    @gen_test
    @requires_database
    async def test_non_query_search(self):

        positive_query = 'bot'

        setup_data = [
            ("ToshiBotA", "toshi bot a", os.urandom(32), True),
            ("ToshiBotB", "toshi bot b", os.urandom(32), True),
            ("ToshiBotC", "toshi bot c", os.urandom(32), True),
            ("ToshiBotD", "toshi bot d", os.urandom(32), True),
            ("ToshiBotE", "toshi bot e", os.urandom(32), True)
        ]

        count = 0
        sessions = []
        for username, name, private_key, featured in setup_data:
            async with self.pool.acquire() as con:
                toshi_id = private_key_to_address(private_key)
                if count > 2:
                    time = datetime.utcnow() - timedelta(minutes=2)
                else:
                    time = datetime.utcnow()
                session_id = uuid.uuid4().hex

                await con.execute("INSERT INTO users (username, name, toshi_id, featured, is_app, is_public) VALUES ($1, $2, $3, $4, $5, $6)",
                                  username, name, toshi_id, featured, True, True)
                await con.execute("INSERT INTO websocket_sessions VALUES ($1, $2, $3)",
                                  session_id, toshi_id, time)
                sessions.append((session_id, toshi_id))
                count += 1

        resp = await self.fetch("/search/apps".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        housekeeping = HousekeepingApplication(
            delay=0.5)
        housekeeping.start()
        await asyncio.sleep(0.1)

        resp = await self.fetch("/search/apps".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 3)

        async with self.pool.acquire() as con:
            await con.execute("UPDATE websocket_sessions SET last_seen = $1", datetime.utcnow() - timedelta(minutes=2))
        await asyncio.sleep(1)

        resp = await self.fetch("/search/apps".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

        housekeeping.shutdown()
