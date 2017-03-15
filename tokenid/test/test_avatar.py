import os
import mimetypes
import blockies
from io import BytesIO

from uuid import uuid4
from tornado import gen
from tornado.escape import json_decode
from tornado.testing import gen_test

from tokenid.app import urls
from tokenid.handlers import generate_username
from asyncbb.test.database import requires_database
from tokenservices.test.base import AsyncHandlerTest
from tokenbrowser.crypto import sign_payload
from tokenbrowser.request import sign_request
from ethutils import data_decoder

TEST_PRIVATE_KEY = data_decoder("0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35")
TEST_ADDRESS = "0x056db290f8ba3250ca64a45d16284d04bc6f5fbf"
TEST_PAYMENT_ADDRESS = "0x444433335555ffffaaaa222211119999ffff7777"

TEST_ADDRESS_2 = "0x056db290f8ba3250ca64a45d16284d04bc000000"

def body_producer(boundary, files):
    buf = BytesIO()
    write = buf.write

    for (filename, data) in files:
        write('--{}\r\n'.format(boundary).encode('utf-8'))
        write('Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
            filename, filename).encode('utf-8'))

        mtype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        write('Content-Type: {}\r\n'.format(mtype).encode('utf-8'))
        write(b'\r\n')
        write(data)
        write(b'\r\n')

    write('--{}--\r\n'.format(boundary).encode('utf-8'))
    return buf.getbuffer().tobytes()

class UserAvatarHandlerTest(AsyncHandlerTest):

    def get_urls(self):
        return urls

    def get_url(self, path):
        if not path.startswith("/avatar"):
            path = "/v1{}".format(path)
        return super().get_url(path)

    @gen_test
    @requires_database
    async def test_update_user_avatar(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id, custom) VALUES ($1, $2, $3)",
                              capitalised, TEST_ADDRESS, "{}")

        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        files = [('image.png', blockies.create(TEST_PAYMENT_ADDRESS, size=8, scale=12, format='PNG'))]
        body = body_producer(boundary, files)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            arow = await con.fetchrow("SELECT * FROM avatars WHERE token_id = $1", TEST_ADDRESS)
            urow = await con.fetchrow("SELECT * FROM users WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(arow)
        self.assertEqual(arow['img'], files[0][1])
        self.assertIsNotNone(urow)
        self.assertIsNotNone(urow['custom'])
        custom = json_decode(urow['custom'])
        self.assertIn('avatar', custom)
        self.assertEqual(custom['avatar'], "/avatar/{}.png".format(TEST_ADDRESS))

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 200)
        self.assertEqual(resp.body, files[0][1])
        self.assertIn('Etag', resp.headers)
        last_etag = resp.headers['Etag']
        self.assertIn('Last-Modified', resp.headers)
        last_modified = resp.headers['Last-Modified']

        # try update
        files = [('image.png', blockies.create(TEST_ADDRESS_2, size=8, scale=12, format='PNG'))]
        body = body_producer(boundary, files)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)
        self.assertResponseCodeEqual(resp, 200)

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': last_etag,
            'If-Modified-Since': last_modified
        })
        self.assertResponseCodeEqual(resp, 200)
        self.assertEqual(resp.body, files[0][1])

        # check for 304 when trying with new values
        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': resp.headers['Etag'],
            'If-Modified-Since': resp.headers['Last-Modified']
        })
        self.assertResponseCodeEqual(resp, 304)

    @gen_test
    @requires_database
    async def test_send_bad_data(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, token_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        files = [('image.png', bytes([0] * 1024))]
        body = body_producer(boundary, files)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)

        self.assertResponseCodeEqual(resp, 400)

        async with self.pool.acquire() as con:
            arow = await con.fetchrow("SELECT * FROM avatars WHERE token_id = $1", TEST_ADDRESS)

        self.assertIsNone(arow)

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 404)
