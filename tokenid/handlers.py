import names as namegenerator
import regex

from asyncbb.handlers import BaseHandler
from asyncbb.errors import JSONHTTPError
from tokenbrowser.utils import flatten_payload
from tokenbrowser.crypto import ecrecover, data_decoder


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

            if not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
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

        elif not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
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
