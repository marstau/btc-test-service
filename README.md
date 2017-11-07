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
heroku buildpacks:add https://github.com/debitoor/ssh-private-key-buildpack.git
heroku buildpacks:add https://github.com/weibeld/heroku-buildpack-run.git
heroku buildpacks:add https://github.com/tristan/heroku-buildpack-pgsql-stunnel.git
heroku buildpacks:add heroku/python

heroku config:set SSH_KEY=$(cat path/to/your/keys/id_rsa | base64)
heroku config:set BUILDPACK_RUN=configure_environment.sh
```

#### Extra Config variables

```
heroku config:set PGSQL_STUNNEL_ENABLED=1
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
