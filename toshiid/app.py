import os
import toshi.web
from toshiid import handlers_v1
from toshiid import websocket
from toshiid import login
from toshiid import search_v2
from toshi.handlers import GenerateTimestamp
import toshi.config

def update_config():
    if 'REPUTATION_SERVICE_ID' in os.environ:
        toshi.config.config['reputation'] = {'id': os.environ['REPUTATION_SERVICE_ID'].lower()}
    if 'SUPERUSER_TOSHI_ID' in os.environ:
        # using a dict because configparser doesn't support lists,
        # and having the toshi id's as keys lets us use `in`.
        toshi.config.config['superusers'] = {
            toshi_id.strip(): 1 for toshi_id in os.environ['SUPERUSER_TOSHI_ID'].lower().split(',')
        }
    if 'APPS_DONT_REQUIRE_WEBSOCKET' in os.environ:
        toshi.config.config['general']['apps_dont_require_websocket'] = os.environ['APPS_DONT_REQUIRE_WEBSOCKET']
    elif 'apps_dont_require_websocket' not in toshi.config.config['general']:
        toshi.config.config['general']['apps_dont_require_websocket'] = 'false'

    if 'APPS_PUBLIC_BY_DEFAULT' in os.environ:
        toshi.config.config['general']['apps_public_by_default'] = os.environ['APPS_PUBLIC_BY_DEFAULT']
    elif 'apps_public_by_default' not in toshi.config.config['general']:
        toshi.config.config['general']['apps_public_by_default'] = 'false'

urls = [

    # #### VERSION 1 #### #

    (r"^/v1/timestamp/?$", GenerateTimestamp),

    # api endpoint for remote login
    (r"^/v1/login/([a-zA-Z0-9]+)/?$", login.LoginHandler),
    (r"^/v1/login/verify/([a-zA-Z0-9]+)/?$", login.WhoDisHandler),

    # standard endpoints
    (r"^/v1/user/?$", handlers_v1.UserCreationHandler),
    (r"^/v1/user/(?P<username>[^/]+)/?$", handlers_v1.UserHandler),
    (r"^/v1/search/user/?$", handlers_v1.SearchUserHandler),
    # app endpoints
    (r"^/v1/apps/(?P<username>0x[a-fA-F0-9]{40})/?$", handlers_v1.UserHandler, {'apps_only': True}),
    (r"^/v1/(?:search/)?apps/?$", handlers_v1.SearchUserHandler, {'force_apps': True}),
    (r"^/v1/(?:search/)?apps/featured/?$", handlers_v1.SearchUserHandler,
     {'force_apps': True, 'force_featured': True}),
    (r"^/v1/(?:search/)?dapps/?$", handlers_v1.SearchDappHandler),

    (r"^/v1/report/?$", handlers_v1.ReportHandler),
    # categories
    (r"^/v1/categories", handlers_v1.CategoryHandler),

    # avatar endpoints
    (r"^/identicon/(?P<address>0x[0-9a-fA-f]{40})\.(?P<format>[a-zA-Z]{3})$", handlers_v1.IdenticonHandler),
    (r"^/avatar/(?P<address>0x[0-9a-fA-f]{40})(?:_(?P<hash>[a-fA-F0-9]+))?\.(?P<format>[a-zA-Z]{3})$", handlers_v1.AvatarHandler),

    # reputation update endpoint
    (r"^/v1/reputation/?$", handlers_v1.ReputationUpdateHandler),

    # websocket
    (r"^/v1/ws/?$", websocket.WebsocketHandler),

    # #### VERSION 2 #### #

    (r"^/v2/user/?$", handlers_v1.UserCreationHandler, {'api_version': 2}),
    (r"^/v2/user/(?P<username>[^/]+)/?$", handlers_v1.UserHandler, {'api_version': 2}),
    (r"^/v2/search/?$", search_v2.SearchHandler),

]

def main():
    update_config()
    app = toshi.web.Application(urls)
    app.start()
