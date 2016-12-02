import tornado.escape
import tornado.web
import traceback
import names as namegenerator
import regex

from .database import HandlerDatabasePoolContext
from .errors import JSONHTTPError
from .utils import flatten_payload
from .utils.crypto import ecrecover, data_decoder


DEFAULT_JSON_ARGUMENT = object()


class BaseHandler(tornado.web.RequestHandler):

    @property
    def db(self):
        if not hasattr(self, '_dbcontext'):
            self._dbcontext = HandlerDatabasePoolContext(self, self.application.connection_pool)
        return self._dbcontext

    @property
    def json(self):
        if not hasattr(self, '_json'):
            data = self.request.body.decode('utf-8').strip()
            self._json = tornado.escape.json_decode(data) if data else {}
        return self._json

    def get_json_argument(self, name, default=DEFAULT_JSON_ARGUMENT):
        if name not in self.json:
            if default is DEFAULT_JSON_ARGUMENT:
                raise JSONHTTPError(400, "missing_arguments")
            return default
        return self.json[name]

    def write_error(self, status_code, **kwargs):
        """Overrides tornado's default error writing handler to return json data instead of a html template"""
        rval = {'type': 'error', 'payload': {}}
        if 'exc_info' in kwargs:
            # check exc type and if JSONHTTPError check for extra details
            exc_type, exc_value, exc_traceback = kwargs['exc_info']
            if isinstance(exc_value, JSONHTTPError):
                if exc_value.body is not None:
                    rval = exc_value.body
                elif exc_value.code is not None:
                    rval['payload']['code'] = exc_value.code
            # if we're in debug mode, add the exception data to the response
            if self.application.config['general'].getboolean('debug'):
                rval['exc_info'] = traceback.format_exception(*kwargs["exc_info"])
        self.write(rval)


class UserCreationHandler(BaseHandler):

    async def post(self):

        if 'payload' not in self.json or 'signature' not in self.json:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        payload = self.json['payload']
        signature = self.json['signature']

        try:
            signature = data_decoder(signature)
        except Exception:
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_signature', 'message': 'Invalid Signature'}]})

        address = ecrecover(flatten_payload(payload), signature)

        if address is None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_signature', 'message': 'Invalid Signature'}]})

        if 'username' in payload:

            username = payload['username']

            if not regex.match('^[a-z0-9_]{1,60}$', username):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

            # check username doesn't already exist
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
            if row is not None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

        else:

            # generate temporary username
            while True:
                username = ''.join(namegenerator.get_full_name().lower().split())
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
                if row is None:
                    break

        async with self.db:
            await self.db.execute("INSERT INTO users (username, eth_address) VALUES ($1, $2)", username, address)
            await self.db.commit()

        self.write({
            'username': username,
            'owner_address': address
        })

class UserHandler(BaseHandler):

    async def get(self, username):

        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE eth_address = $1", username)

        elif not regex.match('^[a-z][a-z0-9_]{1,60}$', username):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        else:
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)

        if row is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        self.write({
            'username': row['username'],
            'owner_address': row['eth_address']
        })
