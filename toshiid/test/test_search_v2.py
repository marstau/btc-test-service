import os
from toshi.test.base import AsyncHandlerTest
from toshiid.app import urls
from toshi.test.database import requires_database
from tornado.testing import gen_test

from tornado.escape import json_decode
from toshiid.search_v2 import GROUPINGS, RESULTS_PER_SECTION
from toshi.ethereum.utils import data_encoder
from urllib.parse import quote as quote_arg

class SearchV2HandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    async def populate_database(self):

        async with self.pool.acquire() as con:
            await con.executemany(
                "INSERT INTO users (toshi_id, username, name, is_bot, is_public, is_groupchatbot, featured) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)", [
                    ("0x0000000000000000000000000000000000000000", "Aaron", "Aaron SEARCH",
                     False, True, False, False),
                    ("0x0000000000000000000000000000000000000001", "Beth", "Beth",
                     False, True, False, False),
                    ("0x0000000000000000000000000000000000000002", "Cynthia", "Cynthia",
                     False, True, False, False),
                    ("0x0000000000000000000000000000000000000003", "Dianne", "Dianne",
                     False, True, False, False),
                    ("0x0000000000000000000000000000000000000004", "Evan", "Evan SEARCH",
                     False, True, False, False),
                    ("0x0000000000000000000000000000000000000005", "Franz", "Franz",
                     False, False, False, False),
                    ("0x0000000000000000000000000000000000000006", "Greg", "Greg SEARCH",
                     False, False, False, False),
                    ("0x0000000000000000000000000000000000000007", "Henry", "Henry SEARCH",
                     False, False, False, False),
                    ("0x0000000000000000000000000000000000000010", "HBot", "H Bot ",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000011", "IBot", "I Bot SEARCH",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000012", "JBot", "J Bot SEARCH",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000013", "KBot", "K Bot",
                     True, True, False, False),
                    ("0x0000000000000000000000000000000000000014", "LBot", "L Bot SEARCH",
                     True, True, False, False),
                    ("0x0000000000000000000000000000000000000015", "MBot", "M Bot",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000016", "NBot", "N Bot SEARCH",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000017", "OBot", "O Bot",
                     True, True, False, True),
                    ("0x0000000000000000000000000000000000000020", "PenguinChat", "Penguin Chat",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000021", "QueenChat", "Queen Chat SEARCH",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000022", "RadioChat", "Radio Chat",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000023", "SnakeChat", "Snake Chat SEARCH",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000024", "TestChat", "Test Chat",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000025", "UltraChat", "Ultra Chat SEARCH",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000026", "VeryChat", "Very Chat SEARCH",
                     True, True, True, True),
                    ("0x0000000000000000000000000000000000000027", "WorkChat", "Work Chat",
                     True, True, True, True),
                ])

    @gen_test
    @requires_database
    async def test_frontpage_search(self):

        await self.populate_database()

        resp = await self.fetch("/v2/search")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)

        self.assertIn('sections', body)
        self.assertEqual(len(body['sections']), len(GROUPINGS))

        for section, (expected_name, expected_query, _) in zip(body['sections'], GROUPINGS):
            self.assertEqual(section['name'], expected_name)
            self.assertEqual(section['query'], expected_query)
            self.assertEqual(len(section['results']), RESULTS_PER_SECTION)

    async def do_test_search(self, type=None, query=None):

        query_string = []
        if type:
            query_string.append("type={}".format(type))
        if query:
            query_string.append("query={}".format(query))
        query_string = '&'.join(query_string)

        resp = await self.fetch("/v2/search?{}".format(query_string))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)

        expected_arguments = ['limit', 'offset', 'total', 'query', 'results']
        self.assertEqual(len(body), len(expected_arguments))
        for arg in expected_arguments:
            self.assertIn(arg, body)

        self.assertEqual(body['query'], query_string)

        if type:
            for result in body['results']:
                self.assertEqual(result['type'], type)
                if query:
                    self.assertIn(query, result['name'].lower())
            if query:
                self.assertEqual(body['total'], 4)
            else:
                self.assertEqual(body['total'], 8)
        else:
            self.fail("TODO")

    @gen_test
    @requires_database
    async def test_bot_search(self):

        await self.populate_database()
        await self.do_test_search('bot')
        await self.do_test_search('bot', 'search')
        await self.do_test_search('bot', 'sear')

    @gen_test
    @requires_database
    async def test_user_search(self):

        await self.populate_database()
        await self.do_test_search('user')
        await self.do_test_search('user', 'search')
        await self.do_test_search('user', 'sear')

    @gen_test
    @requires_database
    async def test_group_search(self):

        await self.populate_database()
        await self.do_test_search('groupbot')
        await self.do_test_search('groupbot', 'search')
        await self.do_test_search('groupbot', 'sear')

    @gen_test(timeout=10)
    @requires_database
    async def test_contact_list_query(self):

        total_users = 10000
        # NOTE: this seems to be the limit for query string length
        # that the server will accept
        query_users = 1255

        users = [(data_encoder(os.urandom(20)), hex(i)) for i in range(total_users)]
        bad_users = [
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "0xcccccccccccccccccccccccccccccccccccccccc"
        ]
        bad_users.extend(user[0] for user in users[:3])

        async with self.pool.acquire() as con:
            await con.executemany("INSERT INTO users (toshi_id, username, active) VALUES ($1, $2, false)",
                                  users)

        resp = await self.fetch("/v2/search/?{}".format("&".join("toshi_id={}".format(toshi_id) for toshi_id, _ in users[:query_users])))

        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertIn('results', body)
        self.assertEqual(len(body['results']), query_users)
        for u, r in zip(users, body['results']):
            self.assertEqual(u[0], r['toshi_id'])

        resp = await self.fetch("/v2/search?{}".format("&".join("toshi_id={}".format(toshi_id) for toshi_id in bad_users)))
        body = json_decode(resp.body)
        self.assertIn('results', body)
        self.assertEqual(len(body['results']), 3)

        # make sure we're safe from injection
        inject = "0')) AS a (id) ON u.toshi_id = a.id; DELETE FROM users; SELECT u.* FROM users u JOIN ( VALUES ('0x0000000000000000000000000000000000000000"
        resp = await self.fetch("/v2/search?toshi_id={}".format(quote_arg(inject)))
        self.assertEqual(resp.code, 400)
