import os

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

class WebsocketHandler(tornado.websocket.WebSocketHandler, DatabaseMixin, RequestVerificationMixin):

    KEEP_ALIVE_TIMEOUT = 30

    @tornado.web.asynchronous
    def get(self, *args, **kwargs):

        self.toshi_id = self.verify_request()
        return super().get(*args, **kwargs)

    def open(self):

        self.io_loop = tornado.ioloop.IOLoop.current()
        self.schedule_ping()
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

    def on_close(self):
        if hasattr(self, '_pingcb'):
            self.io_loop.remove_timeout(self._pingcb)
        self.io_loop.add_callback(self.set_not_connected)

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

        async with self.db:
            await self.db.execute("UPDATE users SET websocket_connection_count = websocket_connection_count + 1 "
                                  "WHERE toshi_id = $1",
                                  self.toshi_id)
            await self.db.commit()

    async def set_not_connected(self):

        async with self.db:
            await self.db.execute("UPDATE users SET websocket_connection_count = websocket_connection_count - 1 "
                                  "WHERE toshi_id = $1",
                                  self.toshi_id)
            await self.db.commit()
