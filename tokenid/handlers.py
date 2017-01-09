import names as namegenerator
import regex

from asyncbb.handlers import BaseHandler
from asyncbb.database import DatabaseMixin
from asyncbb.errors import JSONHTTPError
from tokenservices.handlers import RequestVerificationMixin
from tornado.escape import json_encode

def validate_username(username):
    return regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username)

def user_row_for_json(row):
    return {
        'username': row['username'],
        'owner_address': row['eth_address'],
        'custom': row['custom']
    }

class UserMixin(RequestVerificationMixin):

    async def update_user(self, address):

        if 'payload' not in self.json or 'signature' not in self.json:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        payload = self.json['payload']
        signature = self.json['signature']

        self.verify_payload(address, signature, payload)

        async with self.db:

            # make sure a user with the given address exists
            user = await self.db.fetchrow("SELECT * FROM users WHERE eth_address = $1", address)
            if user is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            if not any(x in payload for x in ['username', 'custom']):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

            if 'username' in payload:
                username = payload['username']
                if not validate_username(username):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

                # make sure the username isn't used by a different user
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1 AND eth_address != $2", username, address)
                if row is not None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

                await self.db.execute("UPDATE users SET username = $1 WHERE eth_address = $2", username, address)
            else:
                username = user['username']

            if 'custom' in payload:
                custom = payload['custom']

                await self.db.execute("UPDATE users SET custom = $1 WHERE eth_address = $2", json_encode(custom), address)
            else:
                custom = user['custom']

            await self.db.commit()

        self.write({
            'username': username,
            'owner_address': address,
            'custom': custom
        })


class UserCreationHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        if 'payload' not in self.json or 'signature' not in self.json or 'address' not in self.json:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        address = self.json['address']
        payload = self.json['payload']
        signature = self.json['signature']

        self.verify_payload(address, signature, payload)

        # check if the address has already registered a username
        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users WHERE eth_address = $1", address)
        if row is not None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided address is already registered'}]})

        if 'username' in payload:

            username = payload['username']

            if not validate_username(username):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

            # check username doesn't already exist
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
            if row is not None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

        else:

            # generate temporary username
            while True:
                username = ''.join(namegenerator.get_full_name().split())
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
                if row is None:
                    break

        custom_json = None
        if 'custom' in self.json:
            custom_json = self.json['custom']

        async with self.db:
            await self.db.execute("INSERT INTO users (username, eth_address, custom) VALUES ($1, $2, $3)", username, address, json_encode(custom_json))
            await self.db.commit()

        self.write({
            'username': username,
            'owner_address': address,
            'custom': custom_json
        })

    def put(self):

        if 'payload' not in self.json or 'signature' not in self.json or 'address' not in self.json:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        expected_address = self.json['address']
        return self.update_user(expected_address)

class UserHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def get(self, username):

        # check if ethereum address is given
        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE eth_address = $1", username)

        # otherwise verify that username is valid
        elif not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        else:
            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)

        if row is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        self.write({
            'username': row['username'],
            'owner_address': row['eth_address'],
            'custom': row['custom']
        })

    async def put(self, username):

        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            return await self.update_user(username)

        elif regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE username = $1", username)
            if row is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            return await self.update_user(row['eth_address'])

        raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})


class SearchUserHandler(UserMixin, DatabaseMixin, BaseHandler):
    async def get(self):
        offset=int(self.get_query_argument('offset', 0, True))
        limit=int(self.get_query_argument('limit', 10, True))
        query=self.get_query_argument('query', None, True)

        if query is None:
            results = []
        else:
            async with self.db:
                rows = await self.db.fetch("""
                SELECT *
                FROM users
                WHERE username LIKE $1
                OFFSET $2
                LIMIT $3
                """, '%'+query+'%', offset, limit)
            results = [user_row_for_json(row) for row in rows]

        self.write({
            'query': query,
            'offset': offset,
            'limit': limit,
            'results': results
        })
