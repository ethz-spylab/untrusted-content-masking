# VWA GitLab Setup

This directory contains the nginx proxy configuration and content-hiding scripts
for running **Visual WebArena's GitLab CE** environment through our untrusted
content masking framework.

## Architecture

```
Agent Container (cua-image)
    │
    │  http://gitlab-vwa.com
    │
    ▼
vwa_gitlab_nginx (OpenResty, port 8103)
    │  ── injects: reveal.js, gitlab-marker.js,
    │              security-tracker.js, html-cache.js
    │
    │  proxy_pass
    │
    ▼
GitLab CE on AWS EC2 (port 8023)          — pre-populated WebArena AMI
```

## Prerequisites

GitLab CE itself runs **on AWS**, not locally — your machine only runs
the Nginx proxy container.

**Local (your machine):**
- Docker and Docker Compose — used to build and run `vwa_gitlab_nginx`.

**AWS (remote):**
- An EC2 instance launched from the WebArena AMI, running the
  pre-populated `gitlab-populated-final-port8023` Docker image (see Setup
  step 1). ~4GB RAM is enough.
- An Elastic IP bound to the instance so the hostname in `nginx.conf`
  stays stable across restarts.

## Setup

### 1. Launch GitLab on AWS

Follow the official [WebArena/VisualWebArena AMI setup](https://github.com/web-arena-x/visualwebarena/blob/main/environment_docker/README.md#pre-installed-amazon-machine-image-recommended)
to launch an EC2 instance from the pre-installed AMI (`webarena-x`, `ami-080f6d73cfce497a1`, region `us-east-2`).

Once the instance is running, SSH in and start only GitLab:
```bash
docker start gitlab
# Wait ~1 min for GitLab to fully start

docker exec gitlab sed -i \
  "s|^external_url.*|external_url 'http://<your-server-hostname>:8023'|" \
  /etc/gitlab/gitlab.rb
docker exec gitlab gitlab-ctl reconfigure
```

Create an Elastic IP and bind it to the instance so the hostname stays stable.

### 2. Configure the Local Nginx Proxy

Fill these four values in the repo-root `.env` file (copy from `.env_example`
on first setup).

| Variable              | What to put                                                 | Where to find it                                                                                       |
| --------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `GITLAB_BACKEND_HOST` | EC2 Elastic IP (or DNS) of your AWS instance                | AWS EC2 console → your instance → "Public IPv4 address" / "Public IPv4 DNS"                            |
| `GITLAB_PUBLIC_HOST`  | FQDN GitLab puts in its own links (matches `external_url`)  | The hostname you used in Step 1's `external_url '…:8023'` command — usually the EC2 public DNS         |
| `GITLAB_SSH_KEY`      | Local path to the `.pem` key that opens the EC2 instance    | The keypair you assigned when launching the EC2 instance (typically `~/.ssh/<keypair-name>.pem`)       |
| `GITLAB_SSH_HOST`     | `ubuntu@<EC2-IP>` — SSH target for `reset_gitlab.sh`        | Same IP as `GITLAB_BACKEND_HOST`, with the AMI's default user `ubuntu` in front                        |

Example shape (use your own values, not these):

```bash
GITLAB_BACKEND_HOST=5.123.45.107
GITLAB_PUBLIC_HOST=ec2-5-123-45-107.us-east-2.compute.amazonaws.com
GITLAB_SSH_KEY=~/.ssh/my-aws-key.pem
GITLAB_SSH_HOST=ubuntu@5.123.45.107
```

The proxy reads these at container start and substitutes them into
[`nginx.conf.template`](nginx.conf.template) via
[`entrypoint.sh`](entrypoint.sh).

### 3. Start the Proxy

From the project root:
```bash
docker compose up -d vwa_gitlab_nginx
```

Verify it works — the proxy should reach AWS GitLab and serve back its login page:
```bash
curl -sL http://localhost:8103 | grep -o '<title>[^<]*</title>'
# expected:
# <title>Sign in · GitLab</title>
```

## Default Credentials

The WebArena GitLab image comes pre-populated with:
- **Agent user:** `byteblaze` (this is who the agent logs in as)
- **Known projects:** `byteblaze/dotfiles`, `a11yproject/a11yproject.com`, and others
- **Admin:** Root user (for administration if needed)

Check the actual users/projects after setup by browsing `http://localhost:8103/explore`.

## Running WebArena Tasks

See [Running tasks → WebArena GitLab](../../../README.md#webarena-gitlab-1)
in the project root README for the main runner
([`runners/run_webarena.sh`](../../../runners/run_webarena.sh)), CLI
flags, and direct invocation examples. See
[Plotting → WebArena](../../../README.md#webarena) in the same README for
result analysis with
[`plot_webarena.py`](../../../src/plot/plot_webarena.py).

## Environment Reset

After running Environment Action tasks (which modify state), reset GitLab on
your AWS instance to the initial state. The
[`reset_gitlab.sh`](../../../src/benchmarks/webarena/reset_gitlab.sh) script
automates the [official WebArena reset
procedure](https://github.com/web-arena-x/visualwebarena/blob/main/environment_docker/README.md#environment-reset):

```bash
bash src/benchmarks/webarena/reset_gitlab.sh
```

The runners under `runners/` reset between runs automatically; this script
is for manual resets.

## Customizing the Marker Script

`nginx-files/gitlab-marker.js` defines which DOM elements are treated as
untrusted content. After setting up the environment, you should:

1. Browse the GitLab instance and inspect the DOM
2. Verify the CSS selectors in `gitlab-marker.js` match the actual elements
3. Adjust selectors if the GitLab version differs from expected

## Files in This Directory

```
gitlab-vwa-setup/
├── README.md                      # This file
├── Dockerfile.nginx               # OpenResty proxy container
├── nginx.conf                     # Proxy config with script injection
└── nginx-files/
    ├── gitlab-marker.js           # GitLab-specific untrusted content marker
    ├── reveal.js                  # Content hiding/revealing logic
    ├── reveal.css                 # Hiding styles
    ├── security-tracker.js        # Event logging for task success
    ├── html-cache.js              # DOM caching for QLLM + URL tracking
    └── auto-login.js              # Auto-login for the agent (byteblaze user)
```
