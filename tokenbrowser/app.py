import asyncio
import asyncpg
import configparser
import os
import tornado.ioloop
import tornado.options
import tornado.web
import urllib
from . import database
from . import handlers

from tornado.log import access_log
from .log import log

def process_config():
    tornado.options.define("config", default="config-localhost.ini", help="configuration file")
    tornado.options.define("port", default=8888, help="port to listen on")
    tornado.options.parse_command_line()

    config = configparser.ConfigParser()
    config.read(tornado.options.options.config)
    # verify config and set default values
    if 'general' not in config:
        config['general'] = {'debug': 'false'}
    elif 'debug' not in config['general']:
        config['debug'] = 'false'

    if 'DATABASE_URL' in os.environ:
        if 'PGSQL_STUNNEL_ENABLED' in os.environ and os.environ['PGSQL_STUNNEL_ENABLED'] == '1':
            p = urllib.parse.urlparse(os.environ['DATABASE_URL'])
            config['database'] = {
                'host': '/tmp/.s.PGSQL.6101',
                'db': p.path[1:]
            }
            if p.username:
                config['database']['username'] = p.username
            if p.password:
                config['database']['password'] = p.password
        else:
            config['database'] = {'dsn': os.environ['DATABASE_URL']}

    return config

class _RequestDispatcher(tornado.web._RequestDispatcher):
    def set_request(self, request):
        super(_RequestDispatcher, self).set_request(request)

class DebuggingApplication(tornado.web.Application):

    def listen(self, *args, **kwargs):
        self._server = super(DebuggingApplication, self).listen(*args, **kwargs)

    def start_request(self, server_conn, request_conn):
        return _RequestDispatcher(self, request_conn)

    def log_request(self, handler):
        super(DebuggingApplication, self).log_request(handler)
        size = self.connection_pool._queue.qsize()
        access_log.info("Stats for Server on port '{}': Active Server connections: {}, DB Connections in pool: {}, DB Pool size: {}".format(
            tornado.options.options.port,
            len(self._server._connections),
            size,
            self.connection_pool._con_count
        ))

async def create_application(config, application_class=tornado.web.Application):

    urls = [
        (r"^/user/?$", handlers.UserCreationHandler),
        (r"^/user/(?P<username>[^/]+)/?$", handlers.UserHandler),
    ]

    application = application_class(urls, debug=config['general'].getboolean('debug'))
    application.config = config
    application.connection_pool = await asyncpg.create_pool(**config['database'])

    async with application.connection_pool.acquire() as con:
        await database.create_tables(con)

    return application

def main(application):
    application.listen(tornado.options.options.port, xheaders=True)
    application.asyncio_loop = asyncio.get_event_loop()
    log.info("Starting HTTP Server on port: {}".format(tornado.options.options.port))
    application.asyncio_loop.run_forever()
