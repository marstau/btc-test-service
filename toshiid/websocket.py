import os
import uuid

import tornado.websocket
import tornado.ioloop

from toshi.database import DatabaseMixin
from toshi.handlers import RequestVerificationMixin
from toshi.jsonrpc.handlers import JsonRPCBase

from toshi.log import log

class ToshiIdJsonRPCHandler(JsonRPCBase, DatabaseMixin):

    def __init__(self, toshi_id, application, request):
        self.toshi_id = toshi_id
        self.application = application
        self.request = request

class WebsocketHandler(tornado.websocket.WebSocketHandler, RequestVerificationMixin):

    KEEP_ALIVE_TIMEOUT = 30
    SESSION_CLOSE_TIMEOUT = 30

    @property
    def connection_pool(self):
        return self.application.connection_pool

    @tornado.web.asynchronous
    def get(self, *args, **kwargs):

        self.toshi_id = self.verify_request()
        return super().get(*args, **kwargs)

    def open(self):

        self.io_loop = tornado.ioloop.IOLoop.current()
        self.schedule_ping()
        self.session_id = uuid.uuid4().hex
        self.io_loop.add_callback(self.set_connected)

    def schedule_ping(self):
        self._pingcb = self.io_loop.call_later(self.KEEP_ALIVE_TIMEOUT, self.send_ping)

    def send_ping(self):
        try:
            self.ping(os.urandom(1))
        except tornado.websocket.WebSocketClosedError:
            pass

    def on_pong(self, data):
        self.schedule_ping()
        self.io_loop.add_callback(self.set_connected)

    def on_close(self):
        if hasattr(self, '_pingcb'):
            self.io_loop.remove_timeout(self._pingcb)
        # only remove after some time to give some leway in brefiely disconnected client
        self.io_loop.call_later(self.SESSION_CLOSE_TIMEOUT, self.set_not_connected)

    async def _on_message(self, message):
        try:
            response = await ToshiIdJsonRPCHandler(
                self.toshi_id, self.application, self)(message)
            if response:
                self.write_message(response)
        except:
            log.exception("unexpected error handling message: {}".format(message))
            raise

    def on_message(self, message):
        if message is None:
            return
        tornado.ioloop.IOLoop.current().add_callback(self._on_message, message)

    async def set_connected(self):

        async with self.connection_pool.acquire() as con:
            await con.execute("INSERT INTO websocket_sessions (websocket_session_id, toshi_id) VALUES ($1, $2) "
                              "ON CONFLICT (websocket_session_id) DO UPDATE "
                              "SET last_seen = (now() AT TIME ZONE 'utc')",
                              self.session_id, self.toshi_id)

    async def set_not_connected(self):

        async with self.connection_pool.acquire() as con:
            await con.execute("DELETE FROM websocket_sessions WHERE websocket_session_id = $1",
                              self.session_id)
