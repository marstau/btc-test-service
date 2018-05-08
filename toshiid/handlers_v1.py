# -*- coding: utf-8 -*-
import asyncio
import asyncpg
import regex
import io
import blockies
import random
import itertools
import string
import datetime
import hashlib

from toshi.database import DatabaseMixin
from toshi.boto import BotoMixin
from toshi.errors import JSONHTTPError
from toshi.config import config
from toshi.log import log
from decimal import Decimal
from toshi.handlers import (BaseHandler,
                            RequestVerificationMixin,
                            SimpleFileHandler)
from toshi.analytics import AnalyticsMixin, encode_id as analytics_encode_id
from tornado.web import HTTPError
from toshi.utils import validate_address, validate_decimal_string, validate_int_string, parse_int
from PIL import Image, ExifTags
from PIL.JpegImagePlugin import get_sampling

from toshiid.handlers_v2 import user_row_for_json as user_row_for_json_v2

assert ExifTags.TAGS[0x0112] == "Orientation"
EXIF_ORIENTATION = 0x0112

# List of punctuation without _ for username search
PUNCTUATION = string.punctuation.replace('_', '')

MIN_AUTOID_LENGTH = 5

AVATAR_URL_HASH_LENGTH = 6

def generate_username(autoid_length):
    """Generate usernames postfixed with a random ID which is a concatenation
    of digits of length `autoid_length`"""

    chars = '0123456789'
    return 'user' + ''.join([random.choice(chars) for x in range(autoid_length)])

def validate_username(username):
    return regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username)

def dapp_row_for_json(request, row):
    rval = {
        'name': row['name'],
        'description': row['description'],
        'url': row['url'],
        'avatar': row['avatar']
    }
    if rval['avatar'].startswith("/"):
        rval['avatar'] = "{}://{}{}".format(
            request.protocol, request.host,
            rval['avatar'])
    return rval

def user_row_for_json(request, row):
    rval = {
        'username': row['username'],
        'token_id': row['toshi_id'],
        'toshi_id': row['toshi_id'],
        'payment_address': row['payment_address'],
        'avatar': row['avatar'] or "/identicon/{}.png".format(row['toshi_id']),
        'name': row['name'],
        'about': row['description'],
        'location': row['location'],
        'is_app': row['is_bot'],
        'public': row['is_public'],
        'reputation_score': float(row['reputation_score']) if row['reputation_score'] is not None else None,
        'average_rating': float(row['average_rating']) if row['average_rating'] is not None else 0,
        'review_count': row['review_count']
    }
    if rval['avatar'].startswith("/"):
        rval['avatar'] = "{}://{}{}".format(
            request.protocol, request.host,
            rval['avatar'])
    if row['is_bot']:
        rval['featured'] = row['featured'] or False
        if 'category_names' in row and 'category_ids' in row:
            rval['categories'] = [{'id': cat[0], 'tag': cat[1], 'name': cat[2]}
                                  for cat in zip(row['category_ids'], row['category_tags'], row['category_names'])
                                  if cat[0] is not None and cat[1] is not None and cat[2] is not None]
        else:
            rval['categories'] = []
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

def create_identitcon(address, format='PNG'):
    if format == 'JPG':
        format = 'JPEG'
    return blockies.create(address, size=8, scale=12, format=format.upper())

class UserMixin(BotoMixin, RequestVerificationMixin, AnalyticsMixin):

    def is_superuser(self, toshi_id):
        return 'superusers' in config and \
            toshi_id in config['superusers']

    def write_user_data(self, user):
        if self.api_version == 1:
            self.write(user_row_for_json(self.request, user))
        elif self.api_version == 2:
            self.write(user_row_for_json_v2(user))
        else:
            raise Exception("Unknown api version")

    async def update_user(self, toshi_id):

        try:
            payload = self.json
        except:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Error decoding data. Expected JSON content'}]})

        if self.api_version == 1:
            is_bot_key = 'is_app'
            description_key = 'about'
        elif self.api_version == 2:
            is_bot_key = 'bot'
            description_key = 'description'
        else:
            raise Exception("Unknown api version")

        if self.api_version == 1 and 'custom' in payload:
            for key in ['name', 'about', 'location']:
                if key in payload['custom']:
                    payload[key] = payload['custom'][key]

        if not any(x in payload for x in ['username', description_key, 'name', 'avatar', 'payment_address', is_bot_key, 'location', 'public', 'categories']):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        async with self.db:

            # make sure a user with the given toshi_id exists
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)

            if user is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            categories = await self.db.fetch("SELECT category_id FROM bot_categories WHERE toshi_id = $1 ORDER BY category_id", toshi_id)
            categories = [row['category_id'] for row in categories]

            if 'username' in payload and user['username'] != payload['username']:
                username = payload['username']
                if not validate_username(username):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

                # check if this is simply the same username with a different case
                if user['username'].lower() != username.lower():
                    # make sure the username isn't used by a different user
                    row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                    if row is not None:
                        raise JSONHTTPError(400, body={'errors': [{'id': 'username_taken', 'message': 'Username Taken'}]})

                await self.db.execute("UPDATE users SET username = $1 WHERE toshi_id = $2", username, toshi_id)

            if 'payment_address' in payload and payload['payment_address'] != user['payment_address']:
                payment_address = payload['payment_address']
                if payment_address is not None and not validate_address(payment_address):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
                await self.db.execute("UPDATE users SET payment_address = $1 WHERE toshi_id = $2", payment_address, toshi_id)

            if is_bot_key in payload and payload[is_bot_key] != user['is_bot']:
                is_bot = parse_boolean(payload[is_bot_key])
                if not isinstance(is_bot, bool):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
                if config['general'].getboolean('apps_public_by_default') and 'public' not in payload:
                    payload['public'] = is_bot
                await self.db.execute("UPDATE users SET is_bot = $1 WHERE toshi_id = $2", is_bot, toshi_id)

            if 'categories' in payload and payload['categories'] != categories:
                updated_categories = await self.db.fetch(
                    "SELECT category_id, tag FROM categories WHERE category_id = ANY($1) OR tag = ANY($2)",
                    [c for c in payload['categories'] if isinstance(c, int)],
                    [c for c in payload['categories'] if isinstance(c, str)])
                if len(updated_categories) != len(payload['categories']):
                    for cat in updated_categories:
                        if cat['category_id'] in payload['categories']:
                            payload['categories'].remove(cat['category_id'])
                        if cat['tag'] in payload['categories']:
                            payload['categories'].remove(cat['tag'])
                    raise JSONHTTPError(400, body={'errors': {
                        'id': 'bad_arguments',
                        'message': "Invalid Categor{}: {}".format(
                            'ies' if len(payload['categories']) > 1 else 'y',
                            ", ".join([str(c) for c in payload['categories']]))}})
                updated_categories = [c['category_id'] for c in updated_categories]
                removed = set(categories).difference(set(updated_categories))
                added = set(updated_categories).difference(set(categories))
                for category_id in removed:
                    await self.db.execute("DELETE FROM bot_categories WHERE category_id = $1 AND toshi_id = $2", category_id, toshi_id)
                for category_id in added:
                    try:
                        await self.db.execute("INSERT INTO bot_categories VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                              category_id, toshi_id)
                    except asyncpg.exceptions.ForeignKeyViolationError:
                        raise JSONHTTPError(400, body={'errors': {'id': 'bad_arguments', 'message': "Invalid Category ID: {}".format(category_id)}})

            if 'public' in payload and payload['public'] != user['is_public']:
                is_public = parse_boolean(payload['public'])
                if not isinstance(is_public, bool):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
                await self.db.execute("UPDATE users SET is_public = $1, went_public = $2 WHERE toshi_id = $3",
                                      is_public, datetime.datetime.utcnow() if is_public else None, toshi_id)

            if 'name' in payload and payload['name'] != user['name']:
                name = payload['name']
                if not isinstance(name, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Name'}]})
                await self.db.execute("UPDATE users SET name = $1 WHERE toshi_id = $2", name, toshi_id)

            if 'avatar' in payload and payload['avatar'] != user['avatar']:
                avatar = payload['avatar']
                if not isinstance(avatar, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Avatar'}]})
                await self.db.execute("UPDATE users SET avatar = $1 WHERE toshi_id = $2", avatar, toshi_id)

            if description_key in payload and payload[description_key] != user['description']:
                description = payload[description_key]
                if not isinstance(description, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid {}'.format(description_key.capitalize())}]})
                await self.db.execute("UPDATE users SET description = $1 WHERE toshi_id = $2", description, toshi_id)

            if 'location' in payload and payload['location'] != user['location']:
                location = payload['location']
                if not isinstance(location, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Location'}]})
                await self.db.execute("UPDATE users SET location = $1 WHERE toshi_id = $2", location, toshi_id)

            if user['active'] is False:
                # mark users as active if their data has been accessed
                await self.db.execute("UPDATE users SET active = true WHERE toshi_id = $1", toshi_id)

            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write_user_data(user)
        self.track(toshi_id, "Edited profile")

    async def update_user_avatar(self, toshi_id):

        # make sure a user with the given address exists
        async with self.db:
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)

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

        boto_key = "public/avatar/{}_{}.{}".format(toshi_id, cache_hash[:AVATAR_URL_HASH_LENGTH], 'jpg' if format == 'JPEG' else 'png')
        async with self.boto:
            await self.boto.put_object(key=boto_key, body=data)
            avatar_url = self.boto.url_for_object(boto_key)

        async with self.db:
            await self.db.execute("UPDATE users SET avatar = $1 WHERE toshi_id = $2", avatar_url, toshi_id)
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write_user_data(user)

        self.track(toshi_id, "Updated avatar")


class UserCreationHandler(UserMixin, DatabaseMixin, BaseHandler):

    def __init__(self, *args, api_version=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_version = api_version

    async def post(self):

        toshi_id = self.verify_request()
        payload = self.json

        # check if the address has already registered a username
        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
        if row is not None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided toshi id address is already registered'}]})

        if self.api_version == 1:
            is_bot_key = 'is_app'
            description_key = 'about'
        elif self.api_version == 2:
            is_bot_key = 'bot'
            description_key = 'description'
        else:
            raise Exception("Unknown api version")

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
                username = generate_username(MIN_AUTOID_LENGTH + i)
                async with self.db:
                    row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
                if row is None:
                    break

        if 'payment_address' in payload:
            payment_address = payload['payment_address']
            # if not validate_address(payment_address):
            #     raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
        else:
            if self.api_version == 1:
                # default to the toshi_id if payment address is not specified
                payment_address = toshi_id
            else:
                # it's valid to have a null payment_address
                payment_address = None

        if is_bot_key in payload:
            is_bot = parse_boolean(payload[is_bot_key])
            if is_bot is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
            if is_bot is True and config['general'].getboolean('apps_public_by_default') and 'public' not in payload:
                payload['public'] = is_bot
        else:
            is_bot = False

        if 'public' in payload:
            is_public = parse_boolean(payload['public'])
            if is_public is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            is_public = False

        if 'avatar' in payload:
            avatar = payload['avatar']
            if not isinstance(avatar, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            avatar = None

        if 'name' in payload:
            name = payload['name']
            if not isinstance(name, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            name = None

        if description_key in payload:
            description = payload[description_key]
            if not isinstance(description, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            description = None

        if 'location' in payload:
            location = payload['location']
            if not isinstance(location, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            location = None

        identicon_address = payment_address or toshi_id
        identicon_data = await self.run_in_executor(create_identitcon, identicon_address)
        key = "public/identicon/{}.png".format(identicon_address)
        async with self.boto:
            await self.boto.put_object(key=key, body=identicon_data)
            if avatar is None:
                avatar = self.boto.url_for_object(key)

        async with self.db:
            await self.db.execute("INSERT INTO users "
                                  "(username, toshi_id, payment_address, name, avatar, is_bot, description, location, is_public) "
                                  "VALUES "
                                  "($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                                  username, toshi_id, payment_address, name, avatar, is_bot, description, location, is_public)
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write_user_data(user)
        self.people_set(toshi_id, {"distinct_id": analytics_encode_id(toshi_id)})
        self.track(toshi_id, "Created account")

    def put(self):
        toshi_id = self.verify_request()

        if not self.request.headers['Content-Type'].startswith('application/json') and not self.request.files:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Expected application/json or multipart/form-data'}]})

        # check for superuser update
        if 'toshi_id' in self.json:

            specific_toshi_id = self.json.pop('toshi_id').lower()

            if toshi_id != specific_toshi_id and not self.is_superuser(toshi_id):
                raise JSONHTTPError(401, body={'errors': [{'id': 'permission_denied', 'message': 'Permission Denied'}]})

            toshi_id = specific_toshi_id

        if self.request.files:
            return self.update_user_avatar(toshi_id)
        else:
            return self.update_user(toshi_id)

class UserHandler(UserMixin, DatabaseMixin, BaseHandler):

    def __init__(self, *args, apps_only=None, api_version=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.apps_only = apps_only
        self.api_version = api_version

    async def get(self, username):

        sql = ("SELECT users.*, array_agg(bot_categories.category_id) AS category_ids, "
               "array_agg(categories.tag) AS category_tags, "
               "array_agg(category_names.name) AS category_names "
               "FROM users LEFT JOIN bot_categories "
               "ON users.toshi_id = bot_categories.toshi_id "
               "LEFT JOIN category_names ON bot_categories.category_id = category_names.category_id "
               "AND category_names.language = $1 "
               "LEFT JOIN categories ON bot_categories.category_id = categories.category_id "
               "WHERE ")
        args = ['en']

        # check if ethereum address is given
        if regex.match('^0x[a-fA-F0-9]{40}$', username):
            sql += "users.toshi_id = $2"
            args.append(username)

        # otherwise verify that username is valid
        elif not regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})
        else:
            sql += "lower(users.username) = lower($2)"
            args.append(username)

        if self.apps_only:
            sql += " AND users.is_bot = $3 AND users.blocked = $4"
            args.extend([True, False])

        sql += " GROUP BY users.toshi_id"

        async with self.db:
            row = await self.db.fetchrow(sql, *args)

        if row is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        self.write_user_data(row)

    async def put(self, username):

        if regex.match('^0x[a-fA-F0-9]{40}$', username):

            address_to_update = username

        elif regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username):

            async with self.db:
                row = await self.db.fetchrow("SELECT * FROM users WHERE lower(username) = lower($1)", username)
            if row is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

            address_to_update = row['toshi_id']

        else:

            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_username', 'message': 'Invalid Username'}]})

        request_address = self.verify_request()

        if not self.request.headers['Content-Type'].startswith('application/json') and not self.request.files:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Expected application/json or multipart/form-data'}]})

        if request_address != address_to_update:

            # check for superuser update
            if not self.is_superuser(request_address):
                raise JSONHTTPError(401, body={'errors': [{'id': 'permission_denied', 'message': 'Permission Denied'}]})

        if self.request.files:
            return await self.update_user_avatar(address_to_update)
        else:
            return await self.update_user(address_to_update)


class SearchUserHandler(AnalyticsMixin, DatabaseMixin, BaseHandler):

    def __init__(self, *args, force_featured=None, force_apps=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_featured = force_featured
        self.force_apps = force_apps

    async def get(self):
        toshi_ids = self.get_query_arguments('toshi_id')
        if len(toshi_ids) > 0:
            return await self.list_users(toshi_ids)
        else:
            return await self.search()

    async def search(self):

        try:
            offset = int(self.get_query_argument('offset', 0))
            limit = int(self.get_query_argument('limit', 10))
        except ValueError:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        query = self.get_query_argument('query', None)
        public = parse_boolean(self.get_query_argument('public', None))
        payment_address = self.get_query_argument('payment_address', None)
        top = parse_boolean(self.get_query_argument('top', None))
        recent = parse_boolean(self.get_query_argument('recent', None))
        categories = self.get_query_arguments('category')
        if len(categories) > 0:
            categories = [int(cat) if validate_int_string(cat) else cat for cat in categories]
            # reduce categoires down to their ids
            async with self.db:
                categories = await self.db.fetch(
                    "SELECT category_id FROM categories WHERE category_id = ANY($1) OR tag = ANY($2)",
                    [c for c in categories if isinstance(c, int)],
                    [c for c in categories if isinstance(c, str)])
            categories = [c['category_id'] for c in categories]
        # if payment_address and not validate_address(payment_address):
        #     raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid payment_address'}]})

        # forece_featured should always infer force_apps
        if self.force_apps or self.force_featured:
            apps = True
            # if force_apps is true, make sure only public apps are returned
            if public is None:
                public = True
        else:
            apps = parse_boolean(self.get_query_argument('apps', None))

        if self.force_featured:
            featured = True
        elif apps:
            # only check featured flag if search is for apps
            featured = self.get_query_argument('featured', None)
            if featured == '' or featured == 'featured':
                featured = True
            else:
                featured = parse_boolean(featured)
        else:
            featured = None

        if apps is True:
            # force featured if recent + apps
            if recent is True:
                featured = True
            # force featured if top + apps
            elif top is True:
                featured = True
            if config['general'].getboolean('apps_dont_require_websocket'):
                check_connected = False
            else:
                check_connected = True
        else:
            check_connected = False

        if query is None:
            sql = ("SELECT users.*, array_agg(bot_categories.category_id) AS category_ids, "
                   "array_agg(categories.tag) AS category_tags, "
                   "array_agg(category_names.name) AS category_names "
                   "FROM users LEFT JOIN bot_categories "
                   "ON users.toshi_id = bot_categories.toshi_id "
                   "LEFT JOIN category_names ON bot_categories.category_id = category_names.category_id "
                   "AND category_names.language = $1 "
                   "LEFT JOIN categories ON bot_categories.category_id = categories.category_id ")
            sql_args = ['en']
            if check_connected:
                sql += "INNER JOIN websocket_sessions ON users.toshi_id = websocket_sessions.toshi_id "
            if payment_address:
                sql += "WHERE active = true AND payment_address = ${} ".format(len(sql_args) + 1)
                sql_args.append(payment_address)
                if apps is not None:
                    sql += "AND is_bot = ${} AND blocked = false ".format(len(sql_args) + 1)
                    sql_args.append(apps)
                    if featured is not None:
                        sql += "AND featured = ${} ".format(len(sql_args) + 1)
                        sql_args.append(featured)
                sql += "GROUP BY users.toshi_id "
                if apps is not None and len(categories) > 0:
                    sql += "HAVING array_agg(bot_categories.category_id) @> ${} ".format(len(sql_args) + 1)
                    sql_args.append(categories)
                if recent:
                    sql += "ORDER BY payment_address, created DESC, name, username "
                else:
                    sql += "ORDER BY payment_address, name, username "
            else:
                if apps is not None:
                    sql += "WHERE is_bot = ${} AND blocked = false ".format(len(sql_args) + 1)
                    sql_args.append(apps)
                    if featured is not None:
                        sql += "AND featured = ${} ".format(len(sql_args) + 1)
                        sql_args.append(featured)
                    if public is not None:
                        sql += "AND is_public = ${} ".format(len(sql_args) + 1)
                        sql_args.append(public)
                elif public is not None:
                    sql += "WHERE is_public = ${} ".format(len(sql_args) + 1)
                    sql_args.append(public)
                    if apps is None or apps is False:
                        sql += "AND is_bot = FALSE "
                sql += "AND active = true "
                sql += "GROUP BY users.toshi_id "
                if apps is not None and len(categories) > 0:
                    sql += "HAVING array_agg(bot_categories.category_id) @> ${} ".format(len(sql_args) + 1)
                    sql_args.append(categories)
                sql += "ORDER BY "
                if top:
                    if recent:
                        if public:
                            sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, went_public DESC NULLS LAST, created DESC, name, username "
                        else:
                            sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, created DESC, name, username "
                    else:
                        sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, name, username "
                elif recent:
                    if public:
                        sql += "went_public DESC NULLS LAST, created DESC, name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
                    else:
                        sql += "created DESC, name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
                else:
                    sql += "name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
            sql += "OFFSET ${} LIMIT ${}".format(len(sql_args) + 1, len(sql_args) + 2)
            sql_args.extend([offset, limit])
        else:
            # strip punctuation
            query = ''.join([" " if c in PUNCTUATION else c for c in query])
            # split words and add in partial matching flags
            query = '|'.join(['{}:*'.format(word) for word in query.split(' ') if word])
            sql_args = ['en', offset, limit, query]
            where_q = []
            if payment_address:
                where_q.append("payment_address = ${}".format(len(sql_args) + 1))
                sql_args.append(payment_address)
            if apps is not None:
                where_q.append("is_bot = ${}".format(len(sql_args) + 1))
                sql_args.append(apps)
                if featured is not None:
                    where_q.append("featured = ${}".format(len(sql_args) + 1))
                    sql_args.append(featured)
                where_q.append("blocked = ${}".format(len(sql_args) + 1))
                sql_args.append(False)
                if len(categories) > 0:
                    for category in categories:
                        where_q.append("bot_categories.category_id = ${}".format(len(sql_args) + 1))
                        sql_args.append(category)
                if public is not None:
                    where_q.append("is_public = ${}".format(len(sql_args) + 1))
                    sql_args.append(public)
            elif public is not None:
                if apps is None or apps is False:
                    # apps shouldn't show up in the public profiles list
                    where_q.append("is_bot = ${}".format(len(sql_args) + 1))
                    sql_args.append(False)
                where_q.append("is_public = ${}".format(len(sql_args) + 1))
                sql_args.append(public)
            where_q.append("active = true")
            where_q = " AND {}".format(" AND ".join(where_q)) if where_q else ""
            sql = ("SELECT * FROM "
                   "(SELECT users.*, array_agg(bot_categories.category_id) AS category_ids, "
                   "array_agg(categories.tag) AS category_tags, "
                   "array_agg(category_names.name) AS category_names "
                   "FROM users {}"
                   "LEFT JOIN bot_categories ON users.toshi_id = bot_categories.toshi_id "
                   "LEFT JOIN category_names ON bot_categories.category_id = category_names.category_id "
                   "AND category_names.language = $1 "
                   "LEFT JOIN categories ON bot_categories.category_id = categories.category_id "
                   ", TO_TSQUERY($4) AS q "
                   "WHERE (tsv @@ q){} "
                   "GROUP BY users.toshi_id ").format(
                       "INNER JOIN websocket_sessions ON users.toshi_id = websocket_sessions.toshi_id "
                       if check_connected else "",
                       where_q)
            if apps is not None and len(categories) > 0:
                sql += "HAVING array_agg(bot_categories.category_id) @> ${} ".format(len(sql_args) + 1)
                sql_args.append(categories)
            sql += ") AS t1 "
            sql += "ORDER BY TS_RANK_CD(t1.tsv, TO_TSQUERY($4)) DESC, "
            if top:
                if recent:
                    if public:
                        sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, went_public DESC NULLS LAST, created DESC, name, username "
                    else:
                        sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, created DESC, name, username "
                else:
                    sql += "COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, name, username "
            elif recent:
                if public:
                    sql += "went_public DESC NULLS LAST, created DESC, name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
                else:
                    sql += "created DESC, name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
            else:
                sql += "name, COALESCE(reputation_score, 2.01) DESC NULLS LAST, review_count DESC, username "
            sql += "OFFSET $2 LIMIT $3 "

        async with self.db:
            rows = await self.db.fetch(sql, *sql_args)
        results = [user_row_for_json(self.request, row) for row in rows]
        querystring = 'query={}'.format(query if query else '')
        if apps is not None:
            querystring += '&apps={}'.format('true' if apps else 'false')
        if payment_address:
            querystring += '&payment_address={}'.format(payment_address)
        if featured is not None:
            querystring += '&featured={}'.format('true' if featured else 'false')
        if public is not None:
            querystring += '&public={}'.format('true' if public else 'false')
        if top is not None:
            querystring += '&top={}'.format('true' if top else 'false')
        for category in categories:
            querystring += '&category={}'.format(category)

        self.write({
            'query': querystring,
            'offset': offset,
            'limit': limit,
            'results': results
        })

        self.track(None, "Searched", {
            "query": query,
            "apps": apps,
            "featured": featured,
            "recent": recent,
            "categories": categories,
            "top": top,
            "public": public,
            "payment_address": payment_address
        })

    async def list_users(self, toshi_ids):

        sql = "SELECT u.* FROM users u JOIN (VALUES "
        values = []
        for i, toshi_id in enumerate(toshi_ids):
            if not validate_address(toshi_id):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
            values.append("('{}', {}) ".format(toshi_id, i))
            # in case this request is made with a lot of ids
            # make sure we yield to other processes rather
            # than taking up all resources on this
            if i > 0 and i % 100 == 0:
                await asyncio.sleep(0.001)
        sql += ", ".join(values)
        sql += ") AS v (toshi_id, ordering) ON u.toshi_id = v.toshi_id "
        sql += "ORDER BY v.ordering"

        async with self.db:
            rows = await self.db.fetch(sql)

        self.write({
            'results': [user_row_for_json(self.request, row) for row in rows]
        })

class SearchDappHandler(AnalyticsMixin, DatabaseMixin, BaseHandler):

    async def get(self):

        async with self.db:
            rows = await self.db.fetch("SELECT * FROM dapps ORDER BY created DESC")

        self.write({
            'results': [dapp_row_for_json(self.request, row) for row in rows]
        })


class IdenticonHandler(DatabaseMixin, SimpleFileHandler):

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

        identicon_pkey = "{}_identicon_{}".format(address, format)
        async with self.db:
            # add suffix to id for cached identicons
            row = await self.db.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1", identicon_pkey)

        if row is None:
            data = blockies.create(address, size=8, scale=12, format=format.upper())
            hasher = hashlib.md5()
            hasher.update(data)
            cache_hash = hasher.hexdigest()
            async with self.db:
                await self.db.execute("INSERT INTO avatars (toshi_id, img, hash, format) VALUES ($1, $2, $3, $4) "
                                      "ON CONFLICT (toshi_id, hash) DO UPDATE "
                                      "SET img = EXCLUDED.img, format = EXCLUDED.format, last_modified = (now() AT TIME ZONE 'utc')",
                                      identicon_pkey, data, cache_hash, format)
                await self.db.commit()
            last_modified = datetime.datetime.utcnow()
        else:
            data = row['img']
            cache_hash = row['hash']
            last_modified = row['last_modified']

        await self.handle_file_response(data, self.FORMAT_MAP[format], cache_hash, last_modified)

class AvatarHandler(DatabaseMixin, SimpleFileHandler):

    def head(self, address, hash, format):
        return self.get(address, hash, format, include_body=False)

    async def get(self, address, hash, format, include_body=True):

        format = format.upper()
        if format not in ['PNG', 'JPG', 'JPEG']:
            raise HTTPError(404)
        if format == 'JPG':
            format = 'JPEG'

        async with self.db:
            if hash is None:
                row = await self.db.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1 AND format = $2 ORDER BY last_modified DESC",
                                             address, format)
            else:
                row = await self.db.fetchrow(
                    "SELECT * FROM avatars WHERE toshi_id = $1 AND format = $2 AND substring(hash for {}) = $3"
                    .format(AVATAR_URL_HASH_LENGTH),
                    address, format, hash)

        if row is None or row['format'] != format:
            raise HTTPError(404)

        await self.handle_file_response(row['img'], "image/{}".format(format.lower()),
                                        row['hash'], row['last_modified'])


class ReportHandler(RequestVerificationMixin, AnalyticsMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        reporter_toshi_id = self.verify_request()

        reportee_toshi_id = None
        if 'toshi_id' in self.json:
            reportee_toshi_id = self.json['toshi_id']
        elif 'token_id' in self.json:
            reportee_toshi_id = self.json['token_id']

        if reportee_toshi_id is None or reportee_toshi_id == reporter_toshi_id:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        if not validate_address(reportee_toshi_id):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_toshi_id', 'message': 'Invalid Toshi ID'}]})

        if 'details' in self.json:
            details = self.json['details']
        else:
            details = None

        async with self.db:
            await self.db.execute("INSERT INTO reports (reporter_toshi_id, reportee_toshi_id, details) VALUES ($1, $2, $3)",
                                  reporter_toshi_id, reportee_toshi_id, details)
            await self.db.commit()

        self.set_status(204)
        self.track(reporter_toshi_id, "Made report")
        self.track(reportee_toshi_id, "Was reported")

class CategoryHandler(DatabaseMixin, BaseHandler):

    async def get(self):

        async with self.db:
            rows = await self.db.fetch("SELECT * FROM categories "
                                       "JOIN category_names ON categories.category_id = category_names.category_id "
                                       "WHERE language = $1 ORDER BY categories.category_id",
                                       'en')

        self.write({
            "categories": [
                {"id": row['category_id'], "tag": row['tag'], "name": row['name']}
                for row in rows
            ]
        })

class ReputationUpdateHandler(RequestVerificationMixin, AnalyticsMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        if 'reputation' not in config or 'id' not in config['reputation']:
            raise HTTPError(404)

        try:
            address = self.verify_request()
        except JSONHTTPError:
            raise HTTPError(404)

        if address != config['reputation']['id']:
            raise HTTPError(404)

        if not all(x in self.json for x in ['toshi_id', 'reputation_score', 'review_count', 'average_rating']):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

        toshi_id = self.json['toshi_id']
        if not validate_address(toshi_id):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_toshi_id', 'message': 'Invalid Toshi Id'}]})

        count = self.json['review_count']
        count = parse_int(count)
        if count is None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_review_count', 'message': 'Invalid Review Count'}]})

        score = self.json['reputation_score']
        if isinstance(score, str) and validate_decimal_string(score):
            score = Decimal(score)
        if not isinstance(score, (int, float, Decimal)):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_reputation_score', 'message': 'Invalid Repuration Score'}]})

        rating = self.json['average_rating']
        if isinstance(rating, str) and validate_decimal_string(rating):
            rating = Decimal(rating)
        if not isinstance(score, (int, float, Decimal)):
            raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_average_rating', 'message': 'Invalid Average Rating'}]})

        async with self.db:
            await self.db.execute("UPDATE users SET reputation_score = $1, review_count = $2, average_rating = $3 WHERE toshi_id = $4",
                                  score, count, rating, toshi_id)
            await self.db.commit()

        self.set_status(204)
