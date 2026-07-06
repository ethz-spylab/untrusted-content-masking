#!/usr/bin/env bash
# Reset GitLab WebArena environment on AWS
# Reference: https://github.com/web-arena-x/visualwebarena/blob/main/environment_docker/README.md#environment-reset
#
# Required env vars (set in .env at the repo root, or exported in your shell):
#   GITLAB_SSH_KEY    — path to the .pem private key for AWS SSH access
#                       (e.g. ~/.ssh/your-aws-key.pem)
#   GITLAB_SSH_HOST   — user@host for SSH (e.g. ubuntu@<aws-ip>)
#   GITLAB_PUBLIC_HOST — FQDN GitLab generates links with, sets external_url
#                        (e.g. ec2-<your-aws-hostname>.compute.amazonaws.com:8023)
#
# Run from the repo root:
#   bash src/benchmarks/webarena/reset_gitlab.sh

set -euo pipefail

# Load .env from the repo root if present.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

: "${GITLAB_SSH_KEY:?GITLAB_SSH_KEY is not set — see .env_example}"
: "${GITLAB_SSH_HOST:?GITLAB_SSH_HOST is not set — see .env_example}"
: "${GITLAB_PUBLIC_HOST:?GITLAB_PUBLIC_HOST is not set — see .env_example}"

# Expand ~ in the key path (env-var values don't expand it automatically).
SSH_KEY="${GITLAB_SSH_KEY/#\~/$HOME}"

echo "=== Stopping and removing GitLab container ==="
ssh -i "$SSH_KEY" "$GITLAB_SSH_HOST" "docker stop gitlab && docker rm gitlab"

echo "=== Starting fresh GitLab container ==="
ssh -i "$SSH_KEY" "$GITLAB_SSH_HOST" "docker run --name gitlab -d -p 8023:8023 gitlab-populated-final-port8023 /opt/gitlab/embedded/bin/runsvdir-start"

echo "=== Waiting ~1 min for GitLab to start ==="
sleep 60

echo "=== Reconfiguring external URL ==="
ssh -i "$SSH_KEY" "$GITLAB_SSH_HOST" "docker exec gitlab sed -i \"s|^external_url.*|external_url 'http://${GITLAB_PUBLIC_HOST}:8023'|\" /etc/gitlab/gitlab.rb"

echo "=== Running gitlab-ctl reconfigure (takes ~1-2 min) ==="
ssh -i "$SSH_KEY" "$GITLAB_SSH_HOST" "docker exec gitlab gitlab-ctl reconfigure"

echo "=== Creating API tokens for wasp_inject.py ==="
ssh -i "$SSH_KEY" "$GITLAB_SSH_HOST" 'docker exec gitlab gitlab-rails runner '\''
admin = User.find(1)
t = admin.personal_access_tokens.create(scopes: [:api], name: "wasp-admin", expires_at: 365.days.from_now)
t.set_token("wasp-admin-token-123")
t.save!
user = User.find_by(username: "byteblaze")
t2 = user.personal_access_tokens.create(scopes: [:api], name: "wasp-user", expires_at: 365.days.from_now)
t2.set_token("wasp-user-token-456")
t2.save!
puts "Created tokens: admin=wasp-admin-token-123 user=wasp-user-token-456"
'\'''

echo "=== GitLab reset complete ==="
