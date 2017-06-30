import asyncio
import unittest
import mimetypes
import blockies
import piexif
import os
from io import BytesIO

from uuid import uuid4
from tornado.escape import json_decode
from tornado.testing import gen_test
from tornado.platform.asyncio import to_asyncio_future
from tornado.ioloop import IOLoop

from toshiid.app import urls
from toshiid.handlers import EXIF_ORIENTATION
from toshi.analytics import encode_id
from toshi.test.database import requires_database
from toshi.test.base import AsyncHandlerTest
from toshi.ethereum.utils import data_decoder

from PIL import Image

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
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)",
                              capitalised, TEST_ADDRESS)

        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        png = blockies.create(TEST_PAYMENT_ADDRESS, size=8, scale=12, format='PNG')
        files = [('image.png', png)]
        body = body_producer(boundary, files)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)

        self.assertResponseCodeEqual(resp, 200)

        async with self.pool.acquire() as con:
            arow = await con.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1", TEST_ADDRESS)
            urow = await con.fetchrow("SELECT * FROM users WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNotNone(arow)
        self.assertEqual(arow['img'], files[0][1])
        self.assertIsNotNone(urow)
        self.assertIsNotNone(urow['avatar'])
        self.assertEqual(urow['avatar'], "/avatar/{}.png".format(TEST_ADDRESS))

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 200)
        # easy to test png, it doesn't change so easily when "double" saved
        self.assertEqual(resp.body, png)
        self.assertIn('Etag', resp.headers)
        last_etag = resp.headers['Etag']
        self.assertIn('Last-Modified', resp.headers)
        last_modified = resp.headers['Last-Modified']

        # try update with jpeg
        jpeg = blockies.create(TEST_ADDRESS_2, size=8, scale=12, format='JPEG')
        # rotate jpeg
        # TODO: figure out if there's actually a way to test that
        # this is working as expected
        jpeg = Image.open(BytesIO(jpeg)).rotate(90)
        stream = BytesIO()
        # generate exif info for rotation
        exif_dict = {"0th": {
            piexif.ImageIFD.XResolution: (jpeg.size[0], 1),
            piexif.ImageIFD.YResolution: (jpeg.size[1], 1),
            piexif.ImageIFD.Orientation: 8
        }}
        jpeg.save(stream, format="JPEG", exif=piexif.dump(exif_dict))
        jpeg = stream.getbuffer().tobytes()
        files = [('image.jpg', jpeg)]
        body = body_producer(boundary, files)
        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)
        self.assertResponseCodeEqual(resp, 200)

        # ensure we got a tracking event
        self.assertEqual((await self.next_tracking_event())[0], encode_id(TEST_ADDRESS))

        resp = await self.fetch("/avatar/{}.jpg".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': last_etag,
            'If-Modified-Since': last_modified
        })
        self.assertResponseCodeEqual(resp, 200)
        # it's impossible to compare the jpegs after being saved a 2nd time
        # so i simply make sure the value isn't the same as the png
        self.assertNotEqual(resp.body, png)

        # check for 304 when trying with new values
        resp304 = await self.fetch("/avatar/{}.jpg".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': resp.headers['Etag'],
            'If-Modified-Since': resp.headers['Last-Modified']
        })
        self.assertResponseCodeEqual(resp304, 304)

        # check that avatar stays after other update
        presp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                        body={
                                            "username": "James123",
                                            "name": "Jamie"
                                        })
        self.assertResponseCodeEqual(presp, 200)
        data = json_decode(presp.body)
        self.assertTrue(data['avatar'].endswith("/avatar/{}.jpg".format(TEST_ADDRESS)))

        # make sure png 404's now
        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET", headers={
            'If-None-Match': resp.headers['Etag'],
            'If-Modified-Since': resp.headers['Last-Modified']
        })
        self.assertResponseCodeEqual(resp, 404)

    @gen_test
    @requires_database
    async def test_send_bad_data(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        files = [('image.png', bytes([0] * 1024))]
        body = body_producer(boundary, files)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)

        self.assertResponseCodeEqual(resp, 400)

        async with self.pool.acquire() as con:
            arow = await con.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNone(arow)

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 404)

    @gen_test
    @requires_database
    async def test_send_bad_filename(self):

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        files = [('', bytes([0] * 1024))]
        body = body_producer(boundary, files)

        resp = await self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                                       body=body, headers=headers)

        self.assertResponseCodeEqual(resp, 400)

        async with self.pool.acquire() as con:
            arow = await con.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1", TEST_ADDRESS)

        self.assertIsNone(arow)

        resp = await self.fetch("/avatar/{}.png".format(TEST_ADDRESS), method="GET")
        self.assertResponseCodeEqual(resp, 404)

    @unittest.skip("test uses too much memory to run on circleci")
    @gen_test(timeout=300)
    @requires_database
    async def test_send_large_file(self):
        """Tests uploading a large avatar and makes sure it doesn't block
        other processes"""

        capitalised = 'BobSmith'

        async with self.pool.acquire() as con:
            await con.execute("INSERT INTO users (username, toshi_id) VALUES ($1, $2)", capitalised, TEST_ADDRESS)

        # saves a generated file in the /tmp dir to speed up
        # multiple runs of the same test
        tmpfile = "/tmp/toshi-testing-large-file-test-2390.jpg"
        if os.path.exists(tmpfile):
            jpeg = open(tmpfile, 'rb').read()
        else:
            # generates a file just under 100mb (100mb being the max size upload supported)
            jpeg = blockies.create(TEST_ADDRESS_2, size=2390, scale=12, format='JPEG')
            with open(tmpfile, 'wb') as f:
                f.write(jpeg)
        print("size: {} MB".format(len(jpeg) / 1024 / 1024))
        boundary = uuid4().hex
        headers = {'Content-Type': 'multipart/form-data; boundary={}'.format(boundary)}
        files = [('avatar.jpg', jpeg)]
        body = body_producer(boundary, files)

        f1 = self.fetch_signed("/user", signing_key=TEST_PRIVATE_KEY, method="PUT",
                               body=body, headers=headers)
        # make sure the avatar upload has begun
        await asyncio.sleep(1)
        f2 = self.fetch("/v1/user/{}".format(TEST_ADDRESS), method="GET")
        def f1done(r):
            assert f2.done()
        def f2done(r):
            assert not f1.done()
        loop = IOLoop.current()
        loop.add_future(f1, f1done)
        loop.add_future(f2, f2done)

        await asyncio.wait([to_asyncio_future(f) for f in [f1, f2]], timeout=5)
