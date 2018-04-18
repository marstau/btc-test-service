import asyncio
from toshi.database import DatabaseMixin
from toshi.handlers import BaseHandler
from toshiid.handlers_v1 import parse_boolean, PUNCTUATION
from toshiid.handlers_v2 import user_row_for_json
from toshi.utils import parse_int, validate_address
from toshi.errors import JSONHTTPError

GROUPINGS = [
    ("Popular Groups", "type=groupbot",
     {'is_groupchatbot': True}),
    ("Featured Bots", "type=bot&featured=true",
     {'is_groupchatbot': False, 'is_bot': True, 'featured': True}),
    ("Public Users", "type=user&public=true",
     {'is_bot': False, 'is_public': True}),
]
RESULTS_PER_SECTION = 5

class SearchHandler(DatabaseMixin, BaseHandler):

    async def get(self):

        if not self.request.query_arguments:
            return await self.frontpage()
        elif 'toshi_id' in self.request.query_arguments:
            return await self.list_users(self.get_query_arguments('toshi_id'))
        return await self.search()

    async def frontpage(self):

        sections = []
        for name, query, args in GROUPINGS:

            items = args.items()
            sql = "SELECT * FROM users WHERE {} ORDER BY reputation_score DESC NULLS LAST, review_count DESC, name LIMIT {}"
            sql = sql.format(
                " AND ".join("{}=${}".format(item[0], idx + 1) for idx, item in enumerate(items)),
                RESULTS_PER_SECTION)
            values = (item[1] for item in items)
            async with self.db:
                results = await self.db.fetch(sql, *values)

            sections.append({
                "name": name,
                "query": query,
                "results": [
                    user_row_for_json(result) for result in results
                ]})

        self.write({'sections': sections})

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
            'limit': len(rows),
            'total': len(rows),
            'offset': 0,
            'query': '',
            'results': [user_row_for_json(row) for row in rows]
        })

    async def search(self):

        search_type = self.get_query_argument('type', None)
        search_query = self.get_query_argument('query', None)
        is_public = parse_boolean(self.get_query_argument('public', None))
        featured = parse_boolean(self.get_query_argument('featured', None))
        limit = parse_int(self.get_query_argument('limit', 20))
        offset = parse_int(self.get_query_argument('offset', 0))

        if search_query:

            search_query = ''.join([" " if c in PUNCTUATION else c for c in search_query])
            # split words and add in partial matching flags
            search_query = '|'.join(['{}:*'.format(word) for word in search_query.split(' ') if word])
            sql = ("SELECT {} FROM users, TO_TSQUERY($1) AS q WHERE (tsv @@ q){} "
                   "{}{}")
            values = [search_query]
            order_by = "ORDER BY TS_RANK_CD(tsv, TO_TSQUERY($1)), reputation_score DESC NULLS LAST, review_count DESC, username"

        else:

            sql = ("SELECT {} FROM users{} "
                   "{}{}")
            values = []
            order_by = "ORDER BY reputation_score DESC NULLS LAST, review_count DESC, username"

        where_params = []

        if search_type is not None:
            is_bot = search_type == 'bot' or search_type == 'groupbot'
            is_groupchatbot = search_type == 'groupbot'

            where_params.append("is_bot = ${}".format(len(values) + 1))
            values.append(is_bot)
            where_params.append("is_groupchatbot = ${}".format(len(values) + 1))
            values.append(is_groupchatbot)

        if is_public is not None:
            where_params.append("is_public = ${}".format(len(values) + 1))
            values.append(is_public)
        if featured is not None:
            where_params.append("featured = ${}".format(len(values) + 1))
            values.append(featured)

        if where_params:
            where_params = " AND ".join(where_params)
            if search_query:
                where_params = " AND " + where_params
            else:
                where_params = " WHERE " + where_params
        else:
            where_params = ""

        paging = " OFFSET ${} LIMIT ${}".format(len(values) + 1, len(values) + 2)

        async with self.db:
            total = await self.db.fetchval(
                sql.format("COUNT(*)", where_params, "", ""), *values)
            values.extend([offset, limit])
            results = await self.db.fetch(
                sql.format("*", where_params, order_by, paging), *values)

        query = []
        for key, values in self.request.query_arguments.items():
            if key in ['limit', 'offset']:
                continue
            query.extend(['{}={}'.format(key, v.decode('utf-8')) for v in values])
        return self.write({
            'limit': limit,
            'offset': offset,
            'total': total,
            'results': [user_row_for_json(r) for r in results],
            'query': "&".join(query)
        })
