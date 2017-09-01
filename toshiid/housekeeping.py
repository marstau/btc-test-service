import asyncio
import logging

from toshi.web import ConfigurationManager
from tornado.ioloop import IOLoop
from toshi.log import configure_logger

DEFAULT_DELAY = 30

log = logging.getLogger("toshiid.housekeeping")

class HousekeepingApplication(ConfigurationManager):

    def __init__(self, *, config=None, connection_pool=None, delay=DEFAULT_DELAY):
        self.ioloop = IOLoop.current()
        if config is None:
            self.config = self.process_config()
        else:
            self.config = config
            self.asyncio_loop = asyncio.get_event_loop()
        if connection_pool is None:
            self.prepare_databases(handle_migration=False)
        else:
            self.connection_pool = connection_pool
        self._schedule = None
        self._delay = delay

        configure_logger(log)

    def process_config(self):
        config = super().process_config()
        config['database']['max_size'] = '1'
        config['database']['min_size'] = '1'
        return config

    def start(self):
        self.ioloop.add_callback(self.run_housekeeping)

    def shutdown(self):
        if self._schedule:
            self.ioloop.remove_timeout(self._schedule)

    def run(self):
        self.start()
        self.asyncio_loop.run_forever()

    def schedule_housekeeping(self):

        self._schedule = self.ioloop.add_timeout(self.ioloop.time() + self._delay, self.run_housekeeping)

    async def run_housekeeping(self):
        async with self.connection_pool.acquire() as con:
            rval = await con.execute("DELETE FROM websocket_sessions "
                                     "WHERE last_seen < (now() AT TIME ZONE 'utc' - interval '60 seconds')")
        if rval != "DELETE 0":
            log.info("Housekeeping cleaned up {} stale sessions".format(rval[7:]))

        self.schedule_housekeeping()

if __name__ == '__main__':
    HousekeepingApplication().run()
