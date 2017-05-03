# -*- coding: utf-8 -*-
import regex
import io
import blockies
import random
import itertools
import email.utils
import string
import datetime
import hashlib
import uuid

from tokenservices.database import DatabaseMixin
from tokenservices.errors import JSONHTTPError
from tokenservices.log import log
from decimal import Decimal
from tokenservices.handlers import BaseHandler, RequestVerificationMixin
from tornado.web import HTTPError
from tokenservices.utils import validate_address, validate_decimal_string, parse_int
from PIL import Image, ExifTags
from PIL.JpegImagePlugin import get_sampling

assert ExifTags.TAGS[0x0112] == "Orientation"
EXIF_ORIENTATION = 0x0112

MIN_AUTOID_LENGTH = 5

def generate_username(autoid_length):
    """Generate usernames postfixed with a random ID which is a concatenation
    of digits of length `autoid_length`"""

    chars = '0123456789'
    return 'user' + ''.join([random.choice(chars) for x in range(autoid_length)])

def validate_username(username):
    return regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username)

def validate_migration_key(key):
    return isinstance(key, str) and regex.match('^([0-9a-fA-F]+)$', key)

def user_row_for_json(request, row):
    rval = {
        'username': row['username'],
        'token_id': row['token_id'],
        'payment_address': row['payment_address'],
        'avatar': row['avatar'] or "/identicon/{}.png".format(row['token_id']),
        'name': row['name'],
        'about': row['about'],
        'location': row['location'],
        'is_app': row['is_app'],
        'reputation_score': float(row['reputation_score']) if row['reputation_score'] is not None else None,
        'review_count': row['review_count']
    }
    if rval['avatar'].startswith("/"):
        rval['avatar'] = "{}://{}{}".format(
            request.protocol, request.host,
            rval['avatar'])
    # backwards compat
    rval['custom'] = {
        'avatar': rval['avatar']
    }
    if rval['name'] is not None:
        rval['custom']['name'] = rval['name']
    if rval['about'] is not None:
        rval['custom']['about'] = rval['about']
    if rval['location'] is not None:
        rval['custom']['location'] = rval['location']
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

def process_image(data, mime_type):
    stream = io.BytesIO(data)
    try:
        img = Image.open(stream)
    except OSError:
        raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid image data'}]})

    if mime_type == 'image/jpeg' and img.format == 'JPEG':
        format = "JPEG"
        subsampling = 'keep'
        # check exif information for orientation
        if hasattr(img, '_getexif'):
            x = img._getexif()
            if x and EXIF_ORIENTATION in x and x[EXIF_ORIENTATION] > 1 and x[EXIF_ORIENTATION] < 9:
                orientation = x[EXIF_ORIENTATION]
                subsampling = get_sampling(img)
                if orientation == 2:
                    # Vertical Mirror
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 3:
                    # Rotation 180°
                    img = img.transpose(Image.ROTATE_180)
                elif orientation == 4:
                    # Horizontal Im
                    img = img.transpose(Image.FLIP_TOP_BOTTOM)
                elif orientation == 5:
                    # Horizontal Im + Rotation 90° CCW
                    img = img.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.ROTATE_90)
                elif orientation == 6:
                    # Rotation 270°
                    img = img.transpose(Image.ROTATE_270)
                elif orientation == 7:
                    # Horizontal Im + Rotation 270°
                    img = img.transpose(Image.FLIP_TOP_BOTTOM).transpose(Image.ROTATE_270)
                elif orientation == 8:
                    # Rotation 90°
                    img = img.transpose(Image.ROTATE_90)
        save_kwargs = {'subsampling': subsampling, 'quality': 85}
    elif mime_type == 'image/png' and img.format == 'PNG':
        format = "PNG"
        save_kwargs = {'icc_profile': img.info.get("icc_profile")}
    else:
        raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Unsupported image format'}]})

    if img.size[0] > 512 or img.size[1] > 512:
        img.thumbnail((512, 512))

    stream = io.BytesIO()
    img.save(stream, format=format, optimize=True, **save_kwargs)

    data = stream.getbuffer().tobytes()
    hasher = hashlib.md5()
    hasher.update(data)
    cache_hash = hasher.hexdigest()

    return data, cache_hash, format

class UserMixin(RequestVerificationMixin):

    async def update_user(self, token_id):

        try:
            payload = self.json
        except:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Error decoding data. Expected JSON content'}]})

        async with self.db:

            # make sure a user with the given token_id exists
            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)
            if user is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            if 'token_id' in payload and payload['token_id'] != token_id:
                # begin migration
                token_id_new = payload['token_id']
                # make sure the new token_id doesn't exist
                existing = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id_new)
                if existing:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided token id address is already registered'}]})
                # check if there are already a migration keys for the original token_id
                keys = await self.db.fetch("SELECT * FROM migrations WHERE token_id_orig = $1", token_id)
                now = datetime.datetime.utcnow()
                migration_key = None
                aborted_migrations = set()
                for key in keys:
                    if not key['complete']:
                        if key['date'] + datetime.timedelta(hours=24) > now:
                            if key['token_id_new'] == token_id_new:
                                migration_key = key['migration_key']
                                continue
                            # prevent spamming the endpoint
                            print(key['date'] + datetime.timedelta(seconds=30), now)
                            if key['date'] + datetime.timedelta(seconds=30) > now:
                                raise JSONHTTPError(429, body={'errors': [
                                    {'id': 'too_many_requests',
                                     'message': 'Wait some time before trying again'}]})
                        aborted_migrations.add(key['migration_key'])
                    else:
                        # make sure the migration wasn't done too recently
                        if key['date'] + datetime.timedelta(hours=24) > now:
                            raise JSONHTTPError(400, body={'errors': [
                                {'id': 'invalid_migration',
                                 'message': 'Cannot migrate more than once in a 24 hour period'}]})
                # check if the original token_id was migrated recently
                key = await self.db.fetchrow("SELECT * FROM migrations "
                                             "WHERE token_id_new = $1 AND complete = true "
                                             "ORDER BY date DESC", token_id)
                if key is not None and key['date'] + datetime.timedelta(hours=24) > now:
                    raise JSONHTTPError(400, body={'errors': [
                        {'id': 'invalid_migration',
                         'message': 'Cannot migrate more than once in a 24 hour period'}]})
                for key in aborted_migrations:
                    await self.db.execute("DELETE FROM migrations where migration_key = $1", key)
                if migration_key is None:
                    migration_key = uuid.uuid4().hex
                    # add new entry
                    await self.db.execute(
                        "INSERT INTO migrations (migration_key, token_id_orig, token_id_new) "
                        "VALUES ($1, $2, $3)",
                        migration_key, token_id, token_id_new)
                await self.db.commit()
                self.write({'migration_key': migration_key})
                return
            # backwards compat
            if 'custom' in payload:
                custom = payload.pop('custom')
                if 'name' in custom:
                    payload['name'] = custom['name']
                if 'avatar' in custom:
                    payload['avatar'] = custom['avatar']
                if 'about' in custom:
                    payload['about'] = custom['about']
                if 'location' in custom:
                    payload['location'] = custom['location']

            if not any(x in payload for x in ['username', 'about', 'name', 'avatar', 'payment_address', 'is_app', 'location']):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

            if 'username' in payload and user['username'] != payload['username']:
                username = payload['username']
                if not validate_username(username):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

                # make sure the username isn't used by a different user
                row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                if row is not None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

                await self.db.execute("UPDATE users SET username = $1 WHERE token_id = $2", username, token_id)

            if 'payment_address' in payload and payload['payment_address'] != user['payment_address']:
                payment_address = payload['payment_address']
                if not validate_address(payment_address):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
                await self.db.execute("UPDATE users SET payment_address = $1 WHERE token_id = $2", payment_address, token_id)

            if 'is_app' in payload and payload['is_app'] != user['is_app']:
                is_app = parse_boolean(payload['is_app'])
                if not isinstance(is_app, bool):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
                await self.db.execute("UPDATE users SET is_app = $1 WHERE token_id = $2", is_app, token_id)

            if 'name' in payload and payload['name'] != user['name']:
                name = payload['name']
                if not isinstance(name, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Name'}]})
                await self.db.execute("UPDATE users SET name = $1 WHERE token_id = $2", name, token_id)

            if 'avatar' in payload and payload['avatar'] != user['avatar']:
                avatar = payload['avatar']
                if not isinstance(avatar, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Avatar'}]})
                await self.db.execute("UPDATE users SET avatar = $1 WHERE token_id = $2", avatar, token_id)

            if 'about' in payload and payload['about'] != user['about']:
                about = payload['about']
                if not isinstance(about, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid About'}]})
                await self.db.execute("UPDATE users SET about = $1 WHERE token_id = $2", about, token_id)

            if 'location' in payload and payload['location'] != user['location']:
                location = payload['location']
                if not isinstance(location, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Location'}]})
                await self.db.execute("UPDATE users SET location = $1 WHERE token_id = $2", location, token_id)

            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))

    async def update_user_avatar(self, token_id):

        # make sure a user with the given address exists
        async with self.db:
            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)

        if user is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        files = self.request.files.values()
        if len(files) != 1:
            raise JSONHTTPError(404, body={'errors': [{'id': 'bad_arguments', 'message': 'Too many files'}]})

        file = next(iter(files))
        if len(file) != 1:
            raise JSONHTTPError(404, body={'errors': [{'id': 'bad_arguments', 'message': 'Too many files'}]})
        data = file[0]['body']
        mime_type = file[0]['content_type']

        data, cache_hash, format = await self.run_in_executor(process_image, data, mime_type)

        async with self.db:
            await self.db.execute("INSERT INTO avatars (token_id, img, hash, format) VALUES ($1, $2, $3, $4) "
                                  "ON CONFLICT (token_id) DO UPDATE "
                                  "SET img = EXCLUDED.img, hash = EXCLUDED.hash, format = EXCLUDED.format, last_modified = (now() AT TIME ZONE 'utc')",
                                  token_id, data, cache_hash, format)
            avatar_url = "/avatar/{}.{}".format(token_id, 'jpg' if format == 'JPEG' else 'png')
            await self.db.execute("UPDATE users SET avatar = $1 WHERE token_id = $2", avatar_url, token_id)
            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))


class UserCreationHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        token_id = self.verify_request()
        payload = self.json

        # check if the address has already registered a username
        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)
        if row is not None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided token id address is already registered'}]})

        migrate_from = None
        if 'migration_key' in payload:
            migration_key = payload.pop('migration_key')
            if not validate_migration_key(migration_key):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_migration_key', 'message': 'Invalid Migration Key'}]})
            async with self.db:
                migration = await self.db.fetchrow("SELECT * FROM migrations WHERE migration_key = $1", migration_key)
                # make sure there is a matching migration key and that it's valid for this request
                if migration is None or \
                   migration['token_id_new'] != token_id or \
                   migration['complete'] is True or \
                   migration['date'] + datetime.timedelta(hours=24) < datetime.datetime.utcnow():
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_migration_key', 'message': 'Invalid Migration Key'}]})
                # make sure the original user still exists
                orig_user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1",
                                                   migration['token_id_orig'])
                if orig_user is None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_migration_key', 'message': 'Invalid Migration Key'}]})
            migrate_from = migration['token_id_orig']

        if 'username' in payload:

            username = payload['username']

            if not validate_username(username):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

            # make sure we're allowed to pass in username with a migrate request
            if migrate_from is None or orig_user['username'] != username:

                # check username doesn't already exist
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                if row is not None:
                    raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

        elif migrate_from is not None:

            username = orig_user['username']

        else:

            # generate temporary username
            for i in itertools.count():
                username = generate_username(MIN_AUTOID_LENGTH + i)
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                if row is None:
                    break

        if 'payment_address' in payload:
            payment_address = payload['payment_address']
            if not validate_address(payment_address):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
        else:
            # default to the token_id if payment address is not specified
            payment_address = token_id

        if 'is_app' in payload:
            is_app = parse_boolean(payload['is_app'])
            if is_app is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            is_app = orig_user['is_app'] if migrate_from else False

        if 'avatar' in payload:
            avatar = payload['avatar']
            if not isinstance(avatar, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            if migrate_from and orig_user['avatar']:
                # if the avatar is a default one, make sure it's updated as well
                avatar = orig_user['avatar']
                m = regex.match("^/(avatar|identicon)/{}\.(png|jpe?g)$".format(migrate_from), avatar)
                if m:
                    avatar = "/{}/{}.{}".format(m.group(1), token_id, m.group(2))
            else:
                avatar = None

        if 'name' in payload:
            name = payload['name']
            if not isinstance(name, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            name = orig_user['name'] if migrate_from else None

        if 'about' in payload:
            about = payload['about']
            if not isinstance(about, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            about = orig_user['about'] if migrate_from else None

        if 'location' in payload:
            location = payload['location']
            if not isinstance(location, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            location = orig_user['location'] if migrate_from else None

        async with self.db:
            if migrate_from:
                await self.db.execute("DELETE FROM users WHERE token_id = $1", migrate_from)
                await self.db.execute("UPDATE avatars SET token_id = $1 WHERE token_id = $2",
                                      token_id, migrate_from)
                await self.db.execute("UPDATE migrations SET complete = true WHERE migration_key = $1",
                                      migration_key)
            await self.db.execute("INSERT INTO users "
                                  "(username, token_id, payment_address, name, avatar, is_app, about, location) "
                                  "VALUES "
                                  "($1, $2, $3, $4, $5, $6, $7, $8)",
                                  username, token_id, payment_address, name, avatar, is_app, about, location)
            user = await self.db.fetchrow("SELECT * FROM users WHERE token_id = $1", token_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))

    def put(self):
        token_id = self.verify_request()

        if self.request.headers['Content-Type'] != 'application/json' and not self.request.files:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Expected application/json or multipart/form-data'}]})

        if self.request.files:
            return self.update_user_avatar(token_id)
        else:
            return self.update_user(token_id)

class UserHandler(UserMixin, DatabaseMixin, BaseHandler):

    def __init__(self, *args, apps_only=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.apps_only = apps_only

    async def get(self, username):

        # check if ethereum address is given
        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            eth_req = True
            sql = "SELECT * FROM users WHERE token_id = $1"
            args = [username]

        # otherwise verify that username is valid
        elif not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        else:

            eth_req = False
            sql = "SELECT * FROM users WHERE lower(username) = lower($1)"
            args = [username]

        if self.apps_only:
            sql += " AND is_app = $2 AND blocked = $3"
            args.extend([True, False])

        while True:
            async with self.db:
                row = await self.db.fetchrow(sql, *args)

            if row is None:
                # if this is an eth address request, check if
                # there is a migrated user
                if eth_req:
                    async with self.db:
                        row = await self.db.fetchrow("SELECT * FROM migrations WHERE "
                                                     "token_id_orig = $1 AND complete = true",
                                                     args[0])
                    if row:
                        args = [row['token_id_new']]
                        continue

                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            self.write(user_row_for_json(self.request, row))
            break

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
        payment_address = self.get_query_argument('payment_address', None)
        if payment_address and not validate_address(payment_address):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid payment_address'}]})

        if query is None:
            if payment_address:
                async with self.db:
                    rows = await self.db.fetch(
                        "SELECT * FROM users WHERE payment_address = $3 "
                        "ORDER BY payment_address, name, username "
                        "OFFSET $1 LIMIT $2",
                        offset, limit, payment_address)
                results = [user_row_for_json(self.request, row) for row in rows]
            else:
                results = []
        else:
            # strip punctuation
            query = ''.join([c for c in query if c not in string.punctuation])
            # split words and add in partial matching flags
            query = '|'.join(['{}:*'.format(word) for word in query.split(' ') if word])
            args = [offset, limit, query]
            where_q = []
            if payment_address:
                where_q.append("payment_address = ${}".format(len(args) + 1))
                args.append(payment_address)
            if apps is not None:
                where_q.append("is_app = ${}".format(len(args) + 1))
                args.append(apps)
            where_q = " AND {}".format(" AND ".join(where_q)) if where_q else ""
            sql = ("SELECT * FROM "
                   "(SELECT * FROM users, TO_TSQUERY($3) AS q "
                   "WHERE (tsv @@ q){}) AS t1 "
                   "ORDER BY TS_RANK_CD(t1.tsv, TO_TSQUERY($3)) DESC, name, username "
                   "OFFSET $1 LIMIT $2"
                   .format(where_q))
            async with self.db:
                rows = await self.db.fetch(sql, *args)
            results = [user_row_for_json(self.request, row) for row in rows]
        querystring = 'query={}'.format(query)
        if apps is not None:
            querystring += '&apps={}'.format('true' if apps else 'false')
        if payment_address:
            querystring += '&payment_address={}'.format(payment_address)

        self.write({
            'query': querystring,
            'offset': offset,
            'limit': limit,
            'results': results
        })

class SearchAppsHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def get(self, force_featured=None):

        try:
            offset = int(self.get_query_argument('offset', 0))
            limit = int(self.get_query_argument('limit', 10))
        except ValueError:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        query = self.get_query_argument('query', None)
        payment_address = self.get_query_argument('payment_address', None)
        if payment_address and not validate_address(payment_address):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid payment_address'}]})

        if force_featured:
            featured = True
        else:
            featured = self.get_query_argument('featured', 'false')
            if featured.lower() == 'false':
                featured = False
            else:
                featured = True

        if query is None:
            where_q = []
            order_by = []
            args = [offset, limit]
            if payment_address:
                where_q.append("payment_address = ${}".format(len(args) + 1))
                args.append(payment_address)
                order_by.append(payment_address)
            if featured:
                where_q.append("featured = ${}".format(len(args) + 1))
                args.append(True)
            where_q.append("blocked = ${}".format(len(args) + 1))
            args.append(False)
            where_q.append("is_app = ${}".format(len(args) + 1))
            args.append(True)
            order_by.extend(['name', 'username'])
            async with self.db:
                sql = ("SELECT * FROM users WHERE {} "
                       "ORDER BY {} "
                       "OFFSET $1 LIMIT $2".format(" AND ".join(where_q), ", ".join(order_by)))
                rows = await self.db.fetch(
                    sql,
                    *args)
            results = [user_row_for_json(self.request, row) for row in rows]
        else:
            # strip punctuation
            query = ''.join([c for c in query if c not in string.punctuation])
            # split words and add in partial matching flags
            query = '|'.join(['{}:*'.format(word) for word in query.split(' ') if word])
            args = [offset, limit, query]
            where_q = []
            if payment_address:
                where_q.append("payment_address = ${}".format(len(args) + 1))
                args.append(payment_address)
            if featured:
                where_q.append("featured = ${}".format(len(args) + 1))
                args.append(True)
            where_q.append("is_app = ${}".format(len(args) + 1))
            args.append(True)
            where_q.append("blocked = ${}".format(len(args) + 1))
            args.append(False)
            where_q.append("is_app = ${}".format(len(args) + 1))
            args.append(True)
            where_q = " AND {}".format(" AND ".join(where_q)) if where_q else ""
            sql = ("SELECT * FROM "
                   "(SELECT * FROM users, TO_TSQUERY($3) AS q "
                   "WHERE (tsv @@ q){}) AS t1 "
                   "ORDER BY TS_RANK_CD(t1.tsv, TO_TSQUERY($3)) DESC, name, username "
                   "OFFSET $1 LIMIT $2"
                   .format(where_q))
            async with self.db:
                rows = await self.db.fetch(sql, *args)
            results = [user_row_for_json(self.request, row) for row in rows]
        querystring = 'query={}'.format(query)
        if payment_address:
            querystring += '&payment_address={}'.format(payment_address)

        self.write({
            'query': querystring,
            'offset': offset,
            'limit': limit,
            'results': results
        })


class SimpleFileHandler(BaseHandler):
    async def handle_file_response(self, data, content_type, etag,
                                   last_modified, include_body=True):

        last_modified = last_modified.replace(microsecond=0)
        self.set_header("Etag", '"{}"'.format(etag))
        self.set_header("Last-Modified", last_modified)
        self.set_header("Content-type", content_type)
        self.set_header("Content-length", len(data))

        if self.request.headers.get("If-None-Match"):
            # check etag
            if self.check_etag_header():
                # return 304
                self.set_status(304)
                return
        else:
            ims_value = self.request.headers.get("If-Modified-Since")
            if ims_value is not None:
                date_tuple = email.utils.parsedate(ims_value)
                if date_tuple is not None:
                    if_since = datetime.datetime(*date_tuple[:6])
                    if if_since >= last_modified:
                        self.set_status(304)
                        return

        if include_body:
            self.write(data)

class IdenticonHandler(SimpleFileHandler):

    FORMAT_MAP = {
        'PNG': 'image/png',
        'JPEG': 'image/jpeg'
    }

    def head(self, address, format):
        return self.get(address, format, include_body=False)

    async def get(self, address, format, include_body=True):
        format = format.upper()
        if format == 'JPG':
            format = 'JPEG'
        if format not in self.FORMAT_MAP.keys():
            raise HTTPError(404)
        data = blockies.create(address, size=8, scale=12, format=format.upper())
        hasher = hashlib.md5()
        hasher.update(data)
        cache_hash = hasher.hexdigest()
        await self.handle_file_response(data, self.FORMAT_MAP[format], cache_hash, datetime.datetime(2017, 1, 1))

class AvatarHandler(DatabaseMixin, SimpleFileHandler):

    def head(self, address, format):
        return self.get(address, format, include_body=False)

    async def get(self, address, format, include_body=True):

        format = format.upper()
        if format not in ['PNG', 'JPG', 'JPEG']:
            raise HTTPError(404)
        if format == 'JPG':
            format = 'JPEG'

        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM avatars WHERE token_id = $1", address)

        if row is None or row['format'] != format:
            raise HTTPError(404)

        await self.handle_file_response(row['img'], "image/{}".format(format.lower()),
                                        row['hash'], row['last_modified'])


class ReportHandler(RequestVerificationMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        reporter_token_id = self.verify_request()

        if 'token_id' not in self.json or self.json['token_id'] == reporter_token_id:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        reportee_token_id = self.json['token_id']

        if not validate_address(reportee_token_id):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_token_id', 'message': 'Invalid Token ID'}]})

        if 'details' in self.json:
            details = self.json['details']
        else:
            details = None

        async with self.db:
            await self.db.execute("INSERT INTO reports (reporter_token_id, reportee_token_id, details) VALUES ($1, $2, $3)",
                                  reporter_token_id, reportee_token_id, details)
            await self.db.commit()

        self.set_status(204)


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
