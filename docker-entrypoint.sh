#!/bin/sh
if [ "$APP_ENV" = "production" ]; then
  exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
else
  exec python -m app
fi
