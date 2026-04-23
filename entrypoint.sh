#!/bin/sh
# Thin entrypoint — bootstrap (migrate/superuser/collectstatic) is handled
# by the one-shot 'init' service in docker-compose.yml.
exec "$@"
