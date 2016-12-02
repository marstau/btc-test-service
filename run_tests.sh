#!/bin/bash
set -euo pipefail
IFS=$'\n\t'
if [ ! -d 'env' ]; then
    echo "setting up virtualenv"
    python3 -m virtualenv env
fi
env/bin/pip -q install -r requirements.txt
env/bin/pip -q install -r requirements-testing.txt
env/bin/python -m tornado.testing discover -s tokenbrowser/test
