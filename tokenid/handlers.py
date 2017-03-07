import regex
import json
import blockies
import random
import itertools

from asyncbb.handlers import BaseHandler
from asyncbb.database import DatabaseMixin
from asyncbb.errors import JSONHTTPError
from decimal import Decimal
from tokenservices.handlers import RequestVerificationMixin
from tornado.escape import json_encode
from tornado.web import HTTPError
from tokenbrowser.utils import validate_address, validate_decimal_string, parse_int

MIN_AUTOID_LENGTH = 5

def generate_username(autoid_length):
    """
    Generate usernames postfixed with a random ID which is a concatenation
    of digits of length `autoid_length`
    """
    chars = '0123456789'
    return 'user'+''.join([random.choice(chars) for x in range(autoid_length)])

def validate_username(username):
    return regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username)

def user_row_for_json(row):
    rval = {
        'username': row['username'],
        'token_id': row['token_id'],
        'payment_address': row['payment_address'],
        'custom': json.loads(row['custom']) if isinstance(row['custom'], str) else (row['custom'] or {}),
        'is_app': row['is_app'],
        'reputation_score': float(row['reputation_score']) if row['reputation_score'] is not None else None,
        'review_count': row['review_count']
    }
    if rval['custom'] is None:
        rval['custom'] = {}
    if 'avatar' not in rval['custom']:
        rval['custom']['avatar'] = "/identicon/{}.png".format(row['token_id'])
    return rval

def parse_boolean(b):
    if isinstance(b, bool):
        return b
    elif isinstance(b, str):
        b = b.lower()
        if b == 'true':
            return True
        elif b == 'false':
            return False
        else:
            return None
    elif isinstance(b, int):
        return bool(b)
    return None

class UserMixin(RequestVerificationMixin):

    async def update_user(self, address):

        payload = self.json

        async with self.db:

            # make sure a user with the given address exists
            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", address)
            if user is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            if not any(x in payload for x in ['username', 'custom', 'payment_address', 'is_app']):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

            if 'username' in payload and user['username'] != payload['username']:
                username = payload['username']
                if not validate_username(username):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

                # make sure the username isn't used by a different user
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
                if row is not None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

                await self.db.execute("UPDATE users SET username = $1 WHERE token_id = $2", username, address)
            else:
                username = user['username']

            if 'payment_address' in payload:
                payment_address = payload['payment_address']
            elif 'custom' in payload and 'payment_address' in payload['custom']:
                payment_address = payload['custom']['payment_address']
            else:
                payment_address = None
            if payment_address:
                if not validate_address(payment_address):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
                await self.db.execute("UPDATE users SET payment_address = $1 WHERE token_id = $2", payment_address, address)
            else:
                payment_address = user['payment_address']

            if 'custom' in payload or 'payment_address' in payload:
                custom = payload.get('custom', user['custom'])
                if 'payment_address' in payload:
                    if custom is None:
                        custom = {}
                    custom['payment_address'] = payment_address
                await self.db.execute("UPDATE users SET custom = $1 WHERE token_id = $2", json_encode(custom), address)
            else:
                custom = user['custom']

            if 'is_app' in payload:
                is_app = parse_boolean(payload['is_app'])
                if not isinstance(is_app, bool):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
                await self.db.execute("UPDATE users SET is_app = $1 WHERE token_id = $2", is_app, address)
            else:
                is_app = user['is_app']

            await self.db.commit()

        if custom is None:
            custom = {}
        if 'avatar' not in custom:
            custom['avatar'] = "/identicon/{}.png".format(address)
        self.write({
            'username': username,
            'token_id': address,
            'payment_address': payment_address,
            'custom': custom,
            'reputation_score': float(user['reputation_score']) if user['reputation_score'] is not None else None,
            'review_count': user['review_count'],
            'is_app': is_app
        })

class UserCreationHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        address = self.verify_request()
        payload = self.json

        # check if the address has already registered a username
        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", address)
        if row is not None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided token id address is already registered'}]})

        if 'username' in payload:

            username = payload['username']

            if not validate_username(username):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

            # check username doesn't already exist
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
            if row is not None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

        else:

            # generate temporary username
            for i in itertools.count():
                username = generate_username(MIN_AUTOID_LENGTH+i)
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                if row is None:
                    break

        custom = {}
        if 'custom' in payload:
            custom = payload['custom']
        # set default avatar
        if 'avatar' not in custom:
            custom['avatar'] = "/identicon/{}.png".format(address)

        if 'payment_address' in payload:
            payment_address = payload['payment_address']
            if not validate_address(payment_address):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
            custom['payment_address'] = payment_address
        elif 'payment_address' in custom:
            payment_address = custom['payment_address']
            if not validate_address(payment_address):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
        else:
            #raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Missing Payment Address'}]})
            # TODO: not required right now
            payment_address = None

        if 'is_app' in payload:
            is_app = parse_boolean(payload['is_app'])
            if is_app is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            is_app = False

        async with self.db:
            await self.db.execute("INSERT INTO users "
                                  "(username, token_id, payment_address, custom, is_app) "
                                  "VALUES "
                                  "($1, $2, $3, $4, $5)",
                                  username, address, payment_address, json_encode(custom), is_app)
            await self.db.commit()

        self.write({
            'username': username,
            'token_id': address,
            'payment_address': payment_address,
            'custom': custom,
            'reputation_score': None,
            'review_count': 0,
            'is_app': is_app
        })

    def put(self):

        address = self.verify_request()
        return self.update_user(address)

class UserHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def get(self, username):

        # check if ethereum address is given
        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", username)

        # otherwise verify that username is valid
        elif not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        else:
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)

        if row is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        self.write(user_row_for_json(row))

    async def put(self, username):

        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            address_to_update = username

        elif regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
            if row is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            address_to_update = row['token_id']

        else:

            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        request_address = self.verify_request()

        if request_address != address_to_update:

            raise JSONHTTPError(401, body={'errors': [{'id': 'permission_denied', 'message': 'Permission Denied'}]})

        return await self.update_user(address_to_update)


class SearchUserHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def get(self):

        try:
            offset = int(self.get_query_argument('offset', 0))
            limit = int(self.get_query_argument('limit', 10))
        except ValueError:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        query = self.get_query_argument('query', None)
        apps = parse_boolean(self.get_query_argument('apps', None))

        if query is None:
            results = []
        else:
            args = [offset, limit]
            sql = "SELECT * FROM users WHERE username ILIKE $3"
            args.append('%' + query + '%')
            if apps is not None:
                sql += " AND is_app = $4"
                args.append(apps)
            sql += " ORDER BY username OFFSET $1 LIMIT $2"

            async with self.db:
                rows = await self.db.fetch(sql, *args)
            results = [user_row_for_json(row) for row in rows]
        querystring = 'query={}'.format(query)
        if apps is not None:
            querystring += '&apps={}'.format('true' if apps else 'false')

        self.write({
            'query': querystring,
            'offset': offset,
            'limit': limit,
            'results': results
        })

class IdenticonHandler(BaseHandler):

    FORMAT_MAP = {
        'PNG': 'image/png',
        'JPG': 'image/jpeg'
    }

    def get(self, address, format):
        format = format.upper()
        if format not in self.FORMAT_MAP.keys():
            raise HTTPError(404)
        data = blockies.create(address, size=8, scale=12, format=format.upper())
        self.set_header("Content-type", self.FORMAT_MAP[format])
        self.set_header("Content-length", len(data))
        self.write(data)

class ReputationUpdateHandler(RequestVerificationMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        if 'reputation' not in self.application.config or 'id' not in self.application.config['reputation']:
            raise HTTPError(404)

        try:
            address = self.verify_request()
        except JSONHTTPError:
            raise HTTPError(404)

        if address != self.application.config['reputation']['id']:
            raise HTTPError(404)

        if not all(x in self.json for x in ['address', 'score', 'count']):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        token_id = self.json['address']
        if not validate_address(token_id):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_address', 'message': 'Invalid Address'}]})

        count = self.json['count']
        count = parse_int(count)
        if count is None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_count', 'message': 'Invalid Count'}]})

        score = self.json['score']
        if isinstance(score, str) and validate_decimal_string(score):
            score = Decimal(score)
        if not isinstance(score, (int, float, Decimal)):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_score', 'message': 'Invalid Score'}]})

        async with self.db:
            await self.db.execute("UPDATE users SET reputation_score = $1, review_count = $2 WHERE token_id = $3",
                                  score, count, token_id)
            await self.db.commit()

        self.set_status(204)
