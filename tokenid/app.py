from . import handlers
from . import login
from asyncbb.web import Application
from tokenservices.handlers import GenerateTimestamp
from tornado.web import StaticFileHandler

urls = [
    (r"^/v1/timestamp/?$", GenerateTimestamp),

    # api endpoint for remote login
    (r"^/v1/login/([a-zA-Z0-9]+)/?$", login.LoginHandler),
    (r"^/v1/login/verify/([a-zA-Z0-9]+)/?$", login.WhoDisHandler),

    (r"^/v1/user/?$", handlers.UserCreationHandler),
    (r"^/v1/user/(?P<username>[^/]+)/?$", handlers.UserHandler),
    (r"^/v1/search/user/?$", handlers.SearchUserHandler),
    (r"^/identicon/(?P<address>0x[0-9a-fA-f]{40})\.(?P<format>[a-zA-Z]{3})$", handlers.IdenticonHandler)
]

def main():
    app = Application(urls)
    app.start()
