#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
if [ ! -d 'env' ]; then
    echo "setting up virtualenv"
    virtualenv -p python3 env
fi
if [ -e requirements-base.txt ]; then
    env/bin/pip -q install -r requirements-base.txt
fi
if [ -e requirements-development.txt ]; then
    env/bin/pip -q install -r requirements-development.txt
fi
if [ -e requirements-testing.txt ]; then
    env/bin/pip -q install -r requirements-testing.txt
fi
env/bin/python -m tornado.testing discover -s toshiid/test
