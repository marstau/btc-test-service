from tornado.testing import gen_test

from toshiid.app import urls
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest

TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"

class UserAvatarHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        if not path.startswith("/identicon"):
            path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_update_user_avatar(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)",
                              capitalised, TEST_ADDRESS)

        resp = await self.fetch("/identicon/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            row = await con.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1",
                                     "{}_identicon_{}".format(TEST_ADDRESS, "PNG"))

        self.assertIsNotNone(row)

        # check caching
        self.assertIn('Etag', resp.headers)
        last_etag = resp.headers['Etag']
        self.assertIn('Last-Modified', resp.headers)
        last_modified = resp.headers['Last-Modified']

        resp = await self.fetch("/identicon/{}.png".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': last_etag,
            'If-Modified-Since': last_modified
        })
        self.assertResponseCodeEqual(resp, 304)
