# -*- coding: utf-8 -*-
import asyncpg
import regex
import io
import blockies
import random
import itertools
import email.utils
import string
import datetime
import hashlib

from toshi.database import DatabaseMixin
from toshi.errors import JSONHTTPError
from toshi.log import log
from decimal import Decimal
from toshi.handlers import BaseHandler, RequestVerificationMixin
from toshi.analytics import AnalyticsMixin, encode_id as analytics_encode_id
from tornado.web import HTTPError
from toshi.utils import validate_address, validate_decimal_string, validate_int_string, parse_int
from PIL import Image, ExifTags
from PIL.JpegImagePlugin import get_sampling

assert ExifTags.TAGS[0x0112] == "Orientation"
EXIF_ORIENTATION = 0x0112

# List of punctuation without _ for username search
PUNCTUATION = string.punctuation.replace('_', '')

MIN_AUTOID_LENGTH = 5

def generate_username(autoid_length):
    """Generate usernames postfixed with a random ID which is a concatenation
    of digits of length `autoid_length`"""

    chars = '0123456789'
    return 'user' + ''.join([random.choice(chars) for x in range(autoid_length)])

def validate_username(username):
    return regex.match('^[a-zA-Z][a-zA-Z0-9_]{2,59}$', username)

def user_row_for_json(request, row):
    rval = {
        'username': row['username'],
        'token_id': row['toshi_id'],
        'toshi_id': row['toshi_id'],
        'payment_address': row['payment_address'],
        'avatar': row['avatar'] or "/identicon/{}.png".format(row['toshi_id']),
        'name': row['name'],
        'about': row['about'],
        'location': row['location'],
        'is_app': row['is_app'],
        'public': row['is_public'] if not row['is_app'] else False,
        'reputation_score': float(row['reputation_score']) if row['reputation_score'] is not None else None,
        'average_rating': float(row['average_rating']) if row['average_rating'] is not None else 0,
        'review_count': row['review_count']
    }
    if rval['avatar'].startswith("/"):
        rval['avatar'] = "{}://{}{}".format(
            request.protocol, request.host,
            rval['avatar'])
    if row['is_app']:
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

class UserMixin(RequestVerificationMixin, AnalyticsMixin):

    def is_superuser(self, toshi_id):
        return 'superusers' in self.application.config and \
            toshi_id in self.application.config['superusers']

    async def update_user(self, toshi_id):

        try:
            payload = self.json
        except:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_data', 'message': 'Error decoding data. Expected JSON content'}]})

        async with self.db:

            # make sure a user with the given toshi_id exists
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            categories = await self.db.fetch("SELECT category_id FROM app_categories WHERE toshi_id = $1 ORDER BY category_id", toshi_id)
            categories = [row['category_id'] for row in categories]
            if user is None:
                raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

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

            if not any(x in payload for x in ['username', 'about', 'name', 'avatar', 'payment_address', 'is_app', 'location', 'public', 'categories']):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})

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
                if not validate_address(payment_address):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
                await self.db.execute("UPDATE users SET payment_address = $1 WHERE toshi_id = $2", payment_address, toshi_id)

            if 'is_app' in payload and payload['is_app'] != user['is_app']:
                is_app = parse_boolean(payload['is_app'])
                if not isinstance(is_app, bool):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
                await self.db.execute("UPDATE users SET is_app = $1 WHERE toshi_id = $2", is_app, toshi_id)

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
                    await self.db.execute("DELETE FROM app_categories WHERE category_id = $1 AND toshi_id = $2", category_id, toshi_id)
                for category_id in added:
                    try:
                        await self.db.execute("INSERT INTO app_categories VALUES ($1, $2) ON CONFLICT DO NOTHING",
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

            if 'about' in payload and payload['about'] != user['about']:
                about = payload['about']
                if not isinstance(about, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid About'}]})
                await self.db.execute("UPDATE users SET about = $1 WHERE toshi_id = $2", about, toshi_id)

            if 'location' in payload and payload['location'] != user['location']:
                location = payload['location']
                if not isinstance(location, str):
                    raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid Location'}]})
                await self.db.execute("UPDATE users SET location = $1 WHERE toshi_id = $2", location, toshi_id)

            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))
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

        async with self.db:
            await self.db.execute("INSERT INTO avatars (toshi_id, img, hash, format) VALUES ($1, $2, $3, $4) "
                                  "ON CONFLICT (toshi_id) DO UPDATE "
                                  "SET img = EXCLUDED.img, hash = EXCLUDED.hash, format = EXCLUDED.format, last_modified = (now() AT TIME ZONE 'utc')",
                                  toshi_id, data, cache_hash, format)
            avatar_url = "/avatar/{}.{}".format(toshi_id, 'jpg' if format == 'JPEG' else 'png')
            await self.db.execute("UPDATE users SET avatar = $1 WHERE toshi_id = $2", avatar_url, toshi_id)
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))
        self.track(toshi_id, "Updated avatar")


class UserCreationHandler(UserMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        toshi_id = self.verify_request()
        payload = self.json

        # check if the address has already registered a username
        async with self.db:
            row = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
        if row is not None:
            raise JSONHTTPError(400, body={'errors': [{'id': 'already_registered', 'message': 'The provided toshi id address is already registered'}]})

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
            if not validate_address(payment_address):
                raise JSONHTTPError(400, body={'errors': [{'id': 'invalid_payment_address', 'message': 'Invalid Payment Address'}]})
        else:
            # default to the toshi_id if payment address is not specified
            payment_address = toshi_id

        if 'is_app' in payload:
            is_app = parse_boolean(payload['is_app'])
            if is_app is None:
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            is_app = False

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

        if 'about' in payload:
            about = payload['about']
            if not isinstance(about, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            about = None

        if 'location' in payload:
            location = payload['location']
            if not isinstance(location, str):
                raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        else:
            location = None

        async with self.db:
            await self.db.execute("INSERT INTO users "
                                  "(username, toshi_id, payment_address, name, avatar, is_app, about, location) "
                                  "VALUES "
                                  "($1, $2, $3, $4, $5, $6, $7, $8)",
                                  username, toshi_id, payment_address, name, avatar, is_app, about, location)
            user = await self.db.fetchrow("SELECT * FROM users WHERE toshi_id = $1", toshi_id)
            await self.db.commit()

        self.write(user_row_for_json(self.request, user))
        self.people_set(toshi_id, {"distinct_id": analytics_encode_id(toshi_id)})
        self.track(toshi_id, "Created account")

    def put(self):
        toshi_id = self.verify_request()

        if self.request.headers['Content-Type'] != 'application/json' and not self.request.files:
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

    def __init__(self, *args, apps_only=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.apps_only = apps_only

    async def get(self, username):

        sql = ("SELECT users.*, array_agg(app_categories.category_id) AS category_ids, "
               "array_agg(categories.tag) AS category_tags, "
               "array_agg(category_names.name) AS category_names "
               "FROM users LEFT JOIN app_categories "
               "ON users.toshi_id = app_categories.toshi_id "
               "LEFT JOIN category_names ON app_categories.category_id = category_names.category_id "
               "AND category_names.language = $1 "
               "LEFT JOIN categories ON app_categories.category_id = categories.category_id "
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
            sql += " AND users.is_app = $3 AND users.blocked = $4"
            args.extend([True, False])

        sql += " GROUP BY users.toshi_id"

        async with self.db:
            row = await self.db.fetchrow(sql, *args)

        if row is None:
            raise JSONHTTPError(404, body={'errors': [{'id': 'not_found', 'message': 'Not Found'}]})

        self.write(user_row_for_json(self.request, row))

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

        if request_address != address_to_update:

            # check for superuser update
            if not self.is_superuser(request_address):
                raise JSONHTTPError(401, body={'errors': [{'id': 'permission_denied', 'message': 'Permission Denied'}]})

        return await self.update_user(address_to_update)


class SearchUserHandler(AnalyticsMixin, DatabaseMixin, BaseHandler):

    def __init__(self, *args, force_featured=None, force_apps=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_featured = force_featured
        self.force_apps = force_apps

    async def get(self):

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
        if payment_address and not validate_address(payment_address):
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Invalid payment_address'}]})

        # forece_featured should always infer force_apps
        if self.force_apps or self.force_featured:
            apps = True
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

        # force featured if recent + apps
        if recent is True and apps is True:
            featured = True

        # force remove public if apps is True
        if apps is True:
            public = None

        if query is None:
            sql = ("SELECT users.*, array_agg(app_categories.category_id) AS category_ids, "
                   "array_agg(categories.tag) AS category_tags, "
                   "array_agg(category_names.name) AS category_names "
                   "FROM users LEFT JOIN app_categories "
                   "ON users.toshi_id = app_categories.toshi_id "
                   "LEFT JOIN category_names ON app_categories.category_id = category_names.category_id "
                   "AND category_names.language = $1 "
                   "LEFT JOIN categories ON app_categories.category_id = categories.category_id ")
            sql_args = ['en']
            if payment_address:
                sql += "WHERE payment_address = ${} ".format(len(sql_args) + 1)
                if apps is not None:
                    sql += "AND is_app = ${} AND blocked = false ".format(len(sql_args) + 1)
                    sql_args.append(apps)
                    if featured is not None:
                        sql += "AND featured = ${} ".format(len(sql_args) + 1)
                        sql_args.append(featured)
                sql += "GROUP BY users.toshi_id "
                if apps is not None and len(categories) > 0:
                    sql += "HAVING array_agg(app_categories.category_id) @> ${} ".format(len(sql_args) + 1)
                    sql_args.append(categories)
                if recent:
                    sql += "ORDER BY payment_address, created DESC, name, username "
                else:
                    sql += "ORDER BY payment_address, name, username "
                sql_args.append(payment_address)
            else:
                if apps is not None:
                    sql += "WHERE is_app = ${} AND blocked = false ".format(len(sql_args) + 1)
                    sql_args.append(apps)
                    if featured is not None:
                        sql += "AND featured = ${} ".format(len(sql_args) + 1)
                        sql_args.append(featured)
                elif public is not None:
                    sql += "WHERE is_public = ${} AND is_app = false ".format(len(sql_args) + 1)
                    sql_args.append(public)
                sql += "GROUP BY users.toshi_id "
                if apps is not None and len(categories) > 0:
                    sql += "HAVING array_agg(app_categories.category_id) @> ${} ".format(len(sql_args) + 1)
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
                where_q.append("is_app = ${}".format(len(sql_args) + 1))
                sql_args.append(apps)
                if featured is not None:
                    where_q.append("featured = ${}".format(len(sql_args) + 1))
                    sql_args.append(featured)
                where_q.append("blocked = ${}".format(len(sql_args) + 1))
                sql_args.append(False)
                if len(categories) > 0:
                    for category in categories:
                        where_q.append("app_categories.category_id = ${}".format(len(sql_args) + 1))
                        sql_args.append(category)
            elif public is not None:
                # apps shouldn't show up in the public profiles list
                where_q.append("is_app = ${}".format(len(sql_args) + 1))
                where_q.append("is_public = ${}".format(len(sql_args) + 2))
                sql_args.extend([False, public])
            where_q = " AND {}".format(" AND ".join(where_q)) if where_q else ""
            sql = ("SELECT * FROM "
                   "(SELECT users.*, array_agg(app_categories.category_id) AS category_ids, "
                   "array_agg(categories.tag) AS category_tags, "
                   "array_agg(category_names.name) AS category_names "
                   "FROM users "
                   "LEFT JOIN app_categories ON users.toshi_id = app_categories.toshi_id "
                   "LEFT JOIN category_names ON app_categories.category_id = category_names.category_id "
                   "AND category_names.language = $1 "
                   "LEFT JOIN categories ON app_categories.category_id = categories.category_id "
                   ", TO_TSQUERY($4) AS q "
                   "WHERE (tsv @@ q){} "
                   "GROUP BY users.toshi_id ").format(where_q)
            if apps is not None and len(categories) > 0:
                sql += "HAVING array_agg(app_categories.category_id) @> ${} ".format(len(sql_args) + 1)
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
                                      "ON CONFLICT (toshi_id) DO UPDATE "
                                      "SET img = EXCLUDED.img, hash = EXCLUDED.hash, format = EXCLUDED.format, last_modified = (now() AT TIME ZONE 'utc')",
                                      identicon_pkey, data, cache_hash, format)
                await self.db.commit()
            last_modified = datetime.datetime.utcnow()
        else:
            data = row['img']
            cache_hash = row['hash']
            last_modified = row['last_modified']

        await self.handle_file_response(data, self.FORMAT_MAP[format], cache_hash, last_modified)

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
            row = await self.db.fetchrow("SELECT * FROM avatars WHERE toshi_id = $1", address)

        if row is None or row['format'] != format:
            raise HTTPError(404)

        await self.handle_file_response(row['img'], "image/{}".format(format.lower()),
                                        row['hash'], row['last_modified'])


class ReportHandler(RequestVerificationMixin, AnalyticsMixin, DatabaseMixin, BaseHandler):

    async def post(self):

        reporter_toshi_id = self.verify_request()

        if 'toshi_id' not in self.json or self.json['toshi_id'] == reporter_toshi_id:
            raise JSONHTTPError(400, body={'errors': [{'id': 'bad_arguments', 'message': 'Bad Arguments'}]})
        reportee_toshi_id = self.json['toshi_id']

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

        if 'reputation' not in self.application.config or 'id' not in self.application.config['reputation']:
            raise HTTPError(404)

        try:
            address = self.verify_request()
        except JSONHTTPError:
            raise HTTPError(404)

        if address != self.application.config['reputation']['id']:
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
