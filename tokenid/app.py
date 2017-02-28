import asyncbb.web
import os
from . import handlers
from . import login
from tokenservices.handlers import GenerateTimestamp

urls = [
    (r"^/v1/timestamp/?$", GenerateTimestamp),

    # api endpoint for remote login
    (r"^/v1/login/([a-zA-Z0-9]+)/?$", login.LoginHandler),
    (r"^/v1/login/verify/([a-zA-Z0-9]+)/?$", login.WhoDisHandler),

    # standard endpoints
    (r"^/v1/user/?$", handlers.UserCreationHandler),
    (r"^/v1/user/(?P<username>[^/]+)/?$", handlers.UserHandler),
    (r"^/v1/search/user/?$", handlers.SearchUserHandler),
    (r"^/identicon/(?P<address>0x[0-9a-fA-f]{40})\.(?P<format>[a-zA-Z]{3})$", handlers.IdenticonHandler),

    # reputation update endpoint
    (r"^/v1/reputation/?$", handlers.ReputationUpdateHandler)
]

class Application(asyncbb.web.Application):

    def process_config(self):
        config = super(Application, self).process_config()

        if 'REPUTATION_SERVICE_ID' in os.environ:
            config['reputation'] = {'id': os.environ['REPUTATION_SERVICE_ID'].lower()}

        return config

def main():
    app = Application(urls)
    app.start()
