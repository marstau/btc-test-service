import os
from tornado.escape import json_decode
from tornado.testing import gen_test
from datetime import datetime

from tokenid.app import urls
from tokenservices.analytics import encode_id
from tokenservices.test.base import AsyncHandlerTest
from tokenservices.test.database import requires_database
from tokenservices.ethereum.utils import private_key_to_address

TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"

class AppsHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_get_app_index(self):
        resp = await self.fetch("/apps/", method="GET")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

        setup_data = [
            ("TokenBotA", TEST_ADDRESS[:-1] + 'f', False, True),
            ("TokenBotB", TEST_ADDRESS[:-1] + 'e', False, True),
            ("FeaturedBotA", TEST_ADDRESS[:-1] + 'd', True, True),
            ("FeaturedBotB", TEST_ADDRESS[:-1] + 'c', True, True),
            ("FeaturedBotC", TEST_ADDRESS[:-1] + 'b', True, True),
            ("NormalUser1", TEST_ADDRESS[:-2] + '00', False, False),
            ("NormalUser2", TEST_ADDRESS[:-2] + '01', False, False),
            ("NormalUser3", TEST_ADDRESS[:-2] + '02', False, False),
        ]

        for username, addr, featured, is_app in setup_data:
            async with self.pool.acquire() as con:
                await con.execute("INSERT INTO users (username, name, token_id, is_app, featured) VALUES ($1, $2, $3, $4, $5)",
                                  username, username, addr, is_app, featured)

        resp = await self.fetch("/apps", method="GET")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        # test /apps/featured
        resp = await self.fetch("/apps/featured", method="GET")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 3)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], None)

        resp = await self.fetch("/apps?featured", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 3)

        for true in ['', 'true', 'featured', 'TRUE', 'True']:

            resp = await self.fetch("/apps?featured={}".format(true), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 3, "Failed to map featured={} to true".format(true))

        for false in ['false', 'FALSE', 'False']:

            resp = await self.fetch("/apps?featured={}".format(false), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 2, "Failed to map featured={} to false".format(false))

    @gen_test
    @requires_database
    async def test_get_app(self):
        username = "TokenBot"
        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, $4)",
                              username, username, TEST_ADDRESS, True)
        resp = await self.fetch("/apps/{}".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 200)

    @gen_test
    @requires_database
    async def test_get_missing_app(self):
        resp = await self.fetch("/apps/{}".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 404)


class SearchAppsHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def fetch(self, url, **kwargs):
        return super(SearchAppsHandlerTest, self).fetch("/v1{}".format(url), **kwargs)

    @gen_test
    @requires_database
    async def test_username_query(self):
        username = "TokenBot"
        positive_query = 'Tok'
        negative_query = 'TickleFight'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, $4)",
                              username, username, TEST_ADDRESS, True)

        resp = await self.fetch("/search/apps?query={}".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 1)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], None)

        resp = await self.fetch("/search/apps?query={}".format(negative_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 0)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], None)

    @gen_test
    @requires_database
    async def test_featured_query(self):

        positive_query = 'bot'

        setup_data = [
            ("TokenBotA", "token bot a", TEST_ADDRESS[:-1] + 'f', False),
            ("TokenBotB", "token bot b", TEST_ADDRESS[:-1] + 'e', False),
            ("FeaturedBotA", "featured token bot a", TEST_ADDRESS[:-1] + 'd', True),
            ("FeaturedBotB", "featured token bot b", TEST_ADDRESS[:-1] + 'c', True),
            ("FeaturedBotC", "featured token bot c", TEST_ADDRESS[:-1] + 'b', True)
        ]

        for username, name, addr, featured in setup_data:
            async with self.pool.acquire() as con:
                await con.execute("INSERT INTO users (username, name, token_id, featured, is_app) VALUES ($1, $2, $3, $4, $5)",
                                  username, name, addr, featured, True)

        resp = await self.fetch("/search/apps?query={}".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        resp = await self.fetch("/search/apps?query={}&featured".format(positive_query), method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 3)

        for true in ['', 'true', 'featured', 'TRUE', 'True']:

            resp = await self.fetch("/search/apps?query={}&featured={}".format(positive_query, true), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 3, "Failed to map featured={} to true".format(true))

        for false in ['false', 'FALSE', 'False']:

            resp = await self.fetch("/search/apps?query={}&featured={}".format(positive_query, false), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 2, "Failed to map featured={} to false".format(false))

    @gen_test
    @requires_database
    async def test_bad_limit_and_offset(self):
        positive_query = 'enb'

        resp = await self.fetch("/search/apps?query={}&offset=x".format(positive_query), method="GET")
        self.assertEqual(resp.code, 400)

        resp = await self.fetch("/search/apps?query={}&limit=x".format(positive_query), method="GET")
        self.assertEqual(resp.code, 400)

    @gen_test(timeout=30)
    @requires_database
    async def test_search_order_by_reputation(self):
        no_of_users_to_generate = 7
        insert_vals = []
        for i in range(0, no_of_users_to_generate):
            key = os.urandom(32)
            name = "TokenBot"
            username = 'tokenbot{}'.format(i)
            insert_vals.append((private_key_to_address(key), username, name, (i / (no_of_users_to_generate - 1)) * 5.0, 10))
        for j in range(i + 1, i + 4):
            key = os.urandom(32)
            name = "TokenBot"
            username = 'tokenbot{}'.format(j)
            insert_vals.append((private_key_to_address(key), username, name, (i / (no_of_users_to_generate - 1)) * 5.0, j))
        # add some users with no score to make sure
        # users who haven't been reviewed appear last
        for k in range(j + 1, j + 2):
            key = os.urandom(32)
            username = 'tokenbot{}'.format(k)
            insert_vals.append((private_key_to_address(key), username, name, None, 0))
        async with self.pool.acquire() as con:
            await con.executemany(
                "INSERT INTO users (token_id, username, name, reputation_score, review_count, is_app) VALUES ($1, $2, $3, $4, $5, TRUE)",
                insert_vals)
        resp = await self.fetch("/search/apps?query=Token&limit={}".format(k + 1), method="GET")
        self.assertEqual(resp.code, 200)
        results = json_decode(resp.body)['results']
        self.assertEqual(len(results), k + 1)
        # make sure that the highest rated "Smith" is first
        previous_rating = 5.1
        previous_count = None
        for user in results:
            rep = 2.01 if user['reputation_score'] is None else user['reputation_score']
            self.assertLessEqual(rep, previous_rating)
            if rep == previous_rating:
                self.assertLessEqual(user['review_count'], previous_count)
            previous_count = user['review_count']
            previous_rating = rep

        # test top search without query
        resp = await self.fetch("/search/apps?top=true&limit={}".format(k + 1), method="GET")
        self.assertEqual(resp.code, 200)
        results = json_decode(resp.body)['results']
        self.assertEqual(len(results), k + 1)
        # make sure that the highest rated "Smith" is first
        previous_rating = 5.1
        previous_count = None
        for user in results:
            rep = 2.01 if user['reputation_score'] is None else user['reputation_score']
            self.assertLessEqual(rep, previous_rating)
            if rep == previous_rating:
                self.assertLessEqual(user['review_count'], previous_count)
            previous_count = user['review_count']
            previous_rating = rep

    @gen_test
    @requires_database
    async def test_app_underscore_username_query(self):

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, true)",
                              "wager_weight", "Wager Weight", "0x0000000000000000000000000000000000000001")
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, true)",
                              "bob_smith", "Robert", "0x0000000000000000000000000000000000000002")
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, true)",
                              "bob_jack", "Jackie", "0x0000000000000000000000000000000000000003")
            await con.execute("INSERT INTO users (username, name, token_id, is_app) VALUES ($1, $2, $3, true)",
                              "user1234", "user1234", "0x0000000000000000000000000000000000000004")

        for positive_query in ["wager", "wager_we", "wager_weight", "bob_smi"]:

            resp = await self.fetch("/search/apps?query={}".format(positive_query), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 1, "Failed to get match for search query: {}".format(positive_query))

        for negative_query in ["wager_foo", "bob_bar", "1234", "bobsmith"]:

            resp = await self.fetch("/search/apps?query={}".format(negative_query), method="GET")
            self.assertEqual(resp.code, 200)
            body = json_decode(resp.body)
            self.assertEqual(len(body['results']), 0, "got unexpected match for search query: {}".format(negative_query))

    @gen_test
    @requires_database
    async def test_recent_query(self):

        setup_data = [
            ("BotA", "token bot a", TEST_ADDRESS[:-1] + 'a', datetime(2017, 1, 1), 3.4, 100),
            ("BotB", "token bot b", TEST_ADDRESS[:-1] + 'b', datetime(2017, 1, 2), 4.9, 50),
            ("BotC", "token bot c", TEST_ADDRESS[:-1] + 'c', datetime(2017, 1, 3), 4.0, 100),
            ("BotD", "token bot d", TEST_ADDRESS[:-1] + 'd', datetime(2017, 1, 4), 4.9, 50),
            ("BotE", "token bot e", TEST_ADDRESS[:-1] + 'e', datetime(2017, 1, 5), 3.4, 100)
        ]

        for username, name, addr, created, rating, rev_count in setup_data:
            async with self.pool.acquire() as con:
                await con.execute("INSERT INTO users (username, name, token_id, created, reputation_score, review_count, is_app) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                                  username, name, addr, created, rating, rev_count, True)

        # check alphabetical search

        resp = await self.fetch("/search/apps", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        for expected, result in zip(setup_data, body['results']):
            self.assertEqual(expected[0], result['username'])

        # check recent search

        resp = await self.fetch("/search/apps?recent=true", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        for expected, result in zip(setup_data[::-1], body['results']):
            self.assertEqual(expected[0], result['username'])

        # check recent + top

        resp = await self.fetch("/search/apps?recent=true&top=true", method="GET")
        self.assertEqual(resp.code, 200)
        body = json_decode(resp.body)
        self.assertEqual(len(body['results']), 5)

        previous_rating = 5.1
        previous_count = None
        previous_date = None
        for user in body['results']:
            created = [x[3] for x in setup_data if x[0] == user['username']][0]
            rep = 2.01 if user['reputation_score'] is None else user['reputation_score']
            self.assertLessEqual(rep, previous_rating)
            if rep == previous_rating:
                self.assertLessEqual(user['review_count'], previous_count)
                if user['review_count'] == previous_count:
                    self.assertLessEqual(created, previous_date)
            previous_count = user['review_count']
            previous_rating = rep
            previous_date = created
