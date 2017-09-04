import names as namegen

from tornado.escape import json_decode
from tornado.testing import gen_test

from toshiid.app import urls
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest
from toshi.ethereum.utils import data_decoder

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x7f0294b53af29ded2b5fa04b6225a1bc334a41e6"


class AppCategoriesTest(AsyncHandlerTest):

    def setUp(self):
        super().setUp(extraconf={'general': {'apps_dont_require_websocket': True}})

    def get_urls(self):
        return urls

    def get_url(self, path):
        path = "/v1{}".format(path)
        return super().get_url(path)

    async def setup_categories(self, *, reverse=False):

        categories = [
            (1, "cat1", "Category1"),
            (2, "cat2", "Category2"),
            (3, "cat3", "Category3"),
            (4, "cat4", "Category4"),
            (5, "cat5", "Category5"),
        ]

        # whether we should reverse the insert order
        if reverse:
            categories.reverse()

        async with self.pool.acquire() as con:
            await con.executemany("INSERT INTO categories VALUES ($1, $2)", [(c[0], c[1]) for c in categories])
            await con.executemany("INSERT INTO category_names (category_id, name) VALUES ($1, $2)",
                                  [(c[0], c[2]) for c in categories])

        return categories

    @gen_test
    @requires_database
    async def test_get_categories(self):

        categories = await self.setup_categories(reverse=True)

        resp = await self.fetch("/categories")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("categories", body)

        # make sure categories are sorted by id
        categories.reverse()
        for expected, result in zip(categories, body["categories"]):
            self.assertEqual(expected[0], result["id"])
            self.assertEqual(expected[1], result["tag"])
            self.assertEqual(expected[2], result["name"])

    @gen_test
    @requires_database
    async def test_set_and_get_app_categories(self):

        username = "toshibot"
        name = "ToshiBot"

        categories = await self.setup_categories()

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username, TEST_ADDRESS, name)
            # set inital categories to make sure they're removed
            await con.executemany("INSERT INTO app_categories VALUES ($1, $2)",
                                  [(3, TEST_ADDRESS),
                                   (4, TEST_ADDRESS)])

        # set by mix of tag and id
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "categories": [1, "cat2"]
        })
        self.assertResponseCodeEqual(resp, 200)

        resp = await self.fetch("/user/{}".format(TEST_ADDRESS))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("categories", body)
        self.assertEqual(len(body['categories']), 2)
        self.assertEqual(body['categories'][0]['name'], categories[0][2])
        self.assertEqual(body['categories'][0]['tag'], categories[0][1])
        self.assertEqual(body['categories'][0]['id'], categories[0][0])
        self.assertEqual(body['categories'][1]['name'], categories[1][2])
        self.assertEqual(body['categories'][1]['tag'], categories[1][1])
        self.assertEqual(body['categories'][1]['id'], categories[1][0])

    @gen_test
    @requires_database
    async def test_set_unknown_categories_fails(self):

        username = "toshibot"
        name = "ToshiBot"

        categories = await self.setup_categories()

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username, TEST_ADDRESS, name)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "categories": [categories[-1][0] + 10, 'badcat']
        })
        self.assertResponseCodeEqual(resp, 400)

        resp = await self.fetch("/user/{}".format(TEST_ADDRESS))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("categories", body)
        self.assertEqual(len(body['categories']), 0)

    @gen_test
    @requires_database
    async def test_cascading_deletes(self):
        """Makes sure that deleting a category removes the app speicific
        entries for that category"""

        username = "toshibot"
        name = "ToshiBot"

        categories = await self.setup_categories()

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username, TEST_ADDRESS, name)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT", body={
            "categories": [1, 2]
        })
        self.assertResponseCodeEqual(resp, 200)

        resp = await self.fetch("/user/{}".format(TEST_ADDRESS))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("categories", body)
        self.assertEqual(len(body['categories']), 2)

        async with self.pool.acquire() as con:
            await con.execute("DELETE FROM categories WHERE category_id = 1 OR category_id = 2")
            namerows = await con.fetchval("SELECT COUNT(*) FROM category_names")
            approws = await con.fetchval("SELECT COUNT(*) FROM app_categories")

        self.assertEqual(namerows, len(categories) - 2)
        self.assertEqual(approws, 0)

        resp = await self.fetch("/user/{}".format(TEST_ADDRESS))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("categories", body)
        self.assertEqual(len(body['categories']), 0)

    @gen_test
    @requires_database
    async def test_user_search_returns_categories(self):

        username = "toshibot"
        name = "ToshiBot"

        categories = await self.setup_categories()

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username, TEST_ADDRESS, name)
            await con.executemany("INSERT INTO app_categories VALUES ($1, $2)",
                                  [(1, TEST_ADDRESS),
                                   (2, TEST_ADDRESS)])
            # TODO: test different insert order

        resp = await self.fetch("/search/user?apps=true")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 1)
        body = body["results"][0]
        self.assertEqual(len(body["categories"]), 2)
        self.assertEqual(body["categories"][0]["name"], categories[0][2])
        self.assertEqual(body['categories'][0]['tag'], categories[0][1])
        self.assertEqual(body["categories"][0]["id"], categories[0][0])
        self.assertEqual(body["categories"][1]["name"], categories[1][2])
        self.assertEqual(body['categories'][1]['tag'], categories[1][1])
        self.assertEqual(body["categories"][1]["id"], categories[1][0])

        resp = await self.fetch("/search/user?apps=true&query={}".format(name))
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 1)
        body = body["results"][0]
        self.assertEqual(len(body["categories"]), 2)
        self.assertEqual(body["categories"][0]["name"], categories[0][2])
        self.assertEqual(body['categories'][0]['tag'], categories[0][1])
        self.assertEqual(body["categories"][0]["id"], categories[0][0])
        self.assertEqual(body["categories"][1]["name"], categories[1][2])
        self.assertEqual(body['categories'][1]['tag'], categories[1][1])
        self.assertEqual(body["categories"][1]["id"], categories[1][0])

    @gen_test
    @requires_database
    async def test_user_search_on_categories(self):

        username = "toshibot"
        name = "ToshiBot"

        categories = await self.setup_categories()

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username, TEST_ADDRESS, name)
            await con.executemany("INSERT INTO app_categories VALUES ($1, $2)",
                                  [(1, TEST_ADDRESS),
                                   (2, TEST_ADDRESS)])
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              username + "1", TEST_PAYMENT_ADDRESS, name)
            await con.executemany("INSERT INTO app_categories VALUES ($1, $2)",
                                  [(2, TEST_PAYMENT_ADDRESS),
                                   (3, TEST_PAYMENT_ADDRESS)])
            await con.execute("INSERT INTO users (username, toshi_id, name, is_app, is_public) VALUES ($1, $2, $3, true, true)",
                              namegen.get_first_name(), TEST_ADDRESS_2, namegen.get_full_name())
            # TODO: test different insert order

        for key in ['1', 'cat1']:
            resp = await self.fetch("/search/apps?category={}".format(key))
            self.assertResponseCodeEqual(resp, 200)
            body = json_decode(resp.body)
            self.assertIn("results", body)
            self.assertEqual(len(body["results"]), 1)
            body = body["results"][0]
            self.assertEqual(len(body["categories"]), 2)
            self.assertEqual(body["categories"][0]["name"], categories[0][2])
            self.assertEqual(body['categories'][0]['tag'], categories[0][1])
            self.assertEqual(body["categories"][0]["id"], categories[0][0])
            self.assertEqual(body["categories"][1]["name"], categories[1][2])
            self.assertEqual(body['categories'][1]['tag'], categories[1][1])
            self.assertEqual(body["categories"][1]["id"], categories[1][0])

        resp = await self.fetch("/search/apps?category=4")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 0)

        resp = await self.fetch("/search/apps?query=toshi&category=2")
        self.assertResponseCodeEqual(resp, 200)
        body = json_decode(resp.body)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 2)
