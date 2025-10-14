#!/bin/bash
set -e
echo "[postdeploy] collectstatic"
source /var/app/venv/*/bin/activate
python manage.py collectstatic --noinput