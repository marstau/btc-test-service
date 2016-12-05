from . import handlers
from asyncbb.web import Application

urls = [
    (r"^/v1/user/?$", handlers.UserCreationHandler),
    (r"^/v1/user/(?P<username>[^/]+)/?$", handlers.UserHandler),
]

def main():

    app = Application(urls)
    app.start()
