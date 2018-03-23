import asyncio

import logging
from toshi.log import configure_logger
from toshi.database import prepare_database, get_database_pool
from toshi.config import config

DEFAULT_DELAY = 30

log = logging.getLogger("toshiid.housekeeping")
if 'database' in config:
    config['database']['max_size'] = '1'
    config['database']['min_size'] = '1'

class HousekeepingApplication:

    def __init__(self, *, delay=DEFAULT_DELAY):
        self._schedule = None
        self._delay = delay

        configure_logger(log)

    def start(self):
        asyncio.get_event_loop().create_task(self._start())

    async def _start(self):
        await prepare_database()
        self._schedule = asyncio.get_event_loop().call_soon(self.run_housekeeping)

    def shutdown(self):
        if self._schedule:
            self._schedule.cancel()

    def run(self):
        self.start()
        asyncio.get_event_loop().run_forever()

    def schedule_housekeeping(self):
        self._schedule = asyncio.get_event_loop().call_later(self._delay, self.run_housekeeping)

    def run_housekeeping(self):
        asyncio.get_event_loop().create_task(self.do_housekeeping())

    async def do_housekeeping(self):
        async with get_database_pool().acquire() as con:
            rval = await con.execute("DELETE FROM websocket_sessions "
                                     "WHERE last_seen < (now() AT TIME ZONE 'utc' - interval '60 seconds')")
        if rval != "DELETE 0":
            log.info("Housekeeping cleaned up {} stale sessions".format(rval[7:]))

        self.schedule_housekeeping()

if __name__ == '__main__':
    HousekeepingApplication().run()
