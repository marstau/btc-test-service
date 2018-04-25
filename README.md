## Running

### Requirements

- Python >= 3.5
- Postgresql >= 9.6

### Setup env

```
virtualenv -p python3 env
env/bin/pip install -r requirements-base.txt
env/bin/pip install -r requirements-development.txt
```

### Running

```
DATABASE_URL=postgres://<postgres-dsn> env/bin/python -m toshiid
```

## Running on heroku

### Add heroku git

```
heroku git:remote -a <heroku-project-name> -r <remote-name>
```

### Config

NOTE: if you have multiple deploys you need to append
`--app <heroku-project-name>` to all the following commands.

#### Addons

```
heroku addons:create heroku-postgresql:hobby-basic

```

#### Buildpacks

```
heroku buildpacks:add https://github.com/weibeld/heroku-buildpack-run.git
heroku buildpacks:add heroku/python

heroku config:set BUILDPACK_RUN=configure_environment.sh
```

#### Extra Config variables

```
heroku config:set REPUTATION_SERVICE_ID=0x...
```

The `Procfile` and `runtime.txt` files required for running on heroku
are provided.

### Start

```
heroku ps:scale web:1
```

## Running tests

A convinience script exists to run all tests:
```
./run_tests.sh
```

To run a single test, use:

```
env/bin/python -m tornado.testing toshiid.test.<test-package>
```

- - -

Copyright &copy; 2017-2018 Toshi Holdings Pte. Ltd. &lt;[https://www.toshi.org/](https://www.toshi.org/)&gt;

"Toshi" is a registered trade mark. This License does not grant
permission to use the trade names, trademarks, service marks, or
product names of the Licensor.

This program is free software: you can redistribute it and/or modify
it under the terms of the version 3 of the GNU Affero General Public License
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see &lt;[https://www.gnu.org/licenses/](http://www.gnu.org/licenses/)&gt;.
