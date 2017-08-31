import toshi.web
import os
from . import handlers
from . import websocket
from . import login
from toshi.handlers import GenerateTimestamp

urls = [
    (r"^/v1/timestamp/?$", GenerateTimestamp),

    # api endpoint for remote login
    (r"^/v1/login/([a-zA-Z0-9]+)/?$", login.LoginHandler),
    (r"^/v1/login/verify/([a-zA-Z0-9]+)/?$", login.WhoDisHandler),

    # standard endpoints
    (r"^/v1/user/?$", handlers.UserCreationHandler),
    (r"^/v1/user/(?P<username>[^/]+)/?$", handlers.UserHandler),
    (r"^/v1/search/user/?$", handlers.SearchUserHandler),
    # app endpoints
    (r"^/v1/apps/(?P<username>0x[a-fA-F0-9]{40})/?$", handlers.UserHandler, {'apps_only': True}),
    (r"^/v1/(?:search/)?apps/?$", handlers.SearchUserHandler, {'force_apps': True}),
    (r"^/v1/(?:search/)?apps/featured/?$", handlers.SearchUserHandler,
     {'force_apps': True, 'force_featured': True}),
    (r"^/v1/report/?$", handlers.ReportHandler),
    # categories
    (r"^/v1/categories", handlers.CategoryHandler),

    # avatar endpoints
    (r"^/identicon/(?P<address>0x[0-9a-fA-f]{40})\.(?P<format>[a-zA-Z]{3})$", handlers.IdenticonHandler),
    (r"^/avatar/(?P<address>0x[0-9a-fA-f]{40})\.(?P<format>[a-zA-Z]{3})$", handlers.AvatarHandler),

    # reputation update endpoint
    (r"^/v1/reputation/?$", handlers.ReputationUpdateHandler),

    # websocket
    (r"^/v1/ws/?$", websocket.WebsocketHandler),
]

class Application(toshi.web.Application):

    def process_config(self):
        config = super(Application, self).process_config()

        if 'REPUTATION_SERVICE_ID' in os.environ:
            config['reputation'] = {'id': os.environ['REPUTATION_SERVICE_ID'].lower()}

        if 'SUPERUSER_TOSHI_ID' in os.environ:
            # using a dict because configparser doesn't support lists,
            # and having the toshi id's as keys lets us use `in`.
            config['superusers'] = {
                toshi_id.strip(): 1 for toshi_id in os.environ['SUPERUSER_TOSHI_ID'].lower().split(',')
            }

        if 'APPS_DONT_REQUIRE_WEBSOCKET' in os.environ:
            config['general']['apps_dont_require_websocket'] = os.environ['APPS_DONT_REQUIRE_WEBSOCKET']
        elif 'apps_dont_require_websocket' not in config['general']:
            config['general']['apps_dont_require_websocket'] = 'false'

        return config

def main():
    app = Application(urls)
    app.start()
