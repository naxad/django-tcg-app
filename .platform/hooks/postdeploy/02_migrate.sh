#!/bin/bash
set -e
echo "[postdeploy] migrate"
source /var/app/venv/*/bin/activate
python manage.py migrate --noinput