from toshi.test.base import AsyncHandlerTest
from toshiid.app import urls
from toshi.test.database import requires_database
from tornado.testing import gen_test

from tornado.escape import json_decode
from toshiid.search_v2 import GROUPINGS, RESULTS_PER_SECTION

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

    @gen_test
    @requires_database
    async def test_user_search(self):

        await self.populate_database()
        await self.do_test_search('user')
        await self.do_test_search('user', 'search')

    @gen_test
    @requires_database
    async def test_group_search(self):

        await self.populate_database()
        await self.do_test_search('groupbot')
        await self.do_test_search('groupbot', 'search')
