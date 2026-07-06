#!/bin/sh
# Substitute ${GITLAB_BACKEND_HOST} and ${GITLAB_PUBLIC_HOST} from the
# container environment into nginx.conf.template, then run nginx.
# Other $variables stay untouched so nginx variables ($http_host, etc.)
# work normally.
set -eu

: "${GITLAB_BACKEND_HOST:?GITLAB_BACKEND_HOST is not set — see .env_example}"
: "${GITLAB_PUBLIC_HOST:?GITLAB_PUBLIC_HOST is not set — see .env_example}"

envsubst '${GITLAB_BACKEND_HOST} ${GITLAB_PUBLIC_HOST}' \
    < /etc/nginx/conf.d/default.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
