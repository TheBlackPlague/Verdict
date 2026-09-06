# Docker deployment

Verdict has two independent images. Build from the **repository root**:

```sh
docker build -f Docker/Server.Dockerfile -t verdict-server:local .
docker build -f Docker/Client.Dockerfile -t verdict-client:local .
```

The server hosts the web UI and coordinates tests. The client compiles engines
and plays games for a server. You can run just the server on ZimaOS and run
clients elsewhere. Both images contain the checked-out source; builds no longer
clone another branch. These image names are local builds, not published registry
images.

## Server setup

Copy the environment example and generate a secret:

```sh
cp Docker/.env.example Docker/.env
docker run --rm --entrypoint python verdict-server:local \
  -c 'import secrets; print(secrets.token_urlsafe(64))'
```

Put the generated value in `VERDICT_SECRET_KEY` in `Docker/.env`. Keep it stable
across container replacements. Set `VERDICT_DATA_PATH` to an absolute persistent
host directory. Add the server's LAN IP and/or hostname to
`VERDICT_ALLOWED_HOSTS`, comma-separated, without schemes or ports.

Create the data directory with ownership **1000:1000**, matching the image user.
For example, if `VERDICT_DATA_PATH=/media/HDD0/AppData/verdict`:

```sh
sudo mkdir -p /media/HDD0/AppData/verdict
sudo chown 1000:1000 /media/HDD0/AppData/verdict
docker compose --env-file Docker/.env -f Docker/compose.server.yml up -d --build
docker compose --env-file Docker/.env -f Docker/compose.server.yml logs -f
```

The path above is an example, not a required location. The relative default
`./data` resolves to `Docker/data`, relative to the Compose file.

The image listens on **8000/tcp**. `VERDICT_PORT` sets the published host port.
Startup applies migrations, collects static files, then runs Gunicorn with one
worker and four threads. The PGN watcher is disabled during initialization and
starts with the web process. The health check requests the login page.

| Persistent container path | Contents |
| --- | --- |
| `/data/db.sqlite3` | Users, tests, results, tuning state and network metadata |
| `/data/Media` | Networks, event logs, pending PGNs and PGN archives |
| `/data/staticfiles` | Collected static assets, regenerated at startup |

Mount the whole `/data` directory so SQLite can create its journal files. Use
one server replica for this SQLite deployment. Stop it before taking a consistent
database/media backup. For an existing installation, follow the
[database upgrade notes](../Documentation/upstream-sync.md#upgrading-an-existing-verdict-database)
on a copy before starting the image: copy the old database and complete `Media`
directory into the corresponding paths above. Startup does not fake migrations
or reconcile unknown local migration histories.

### First administrator

Once the server is healthy:

```sh
docker compose --env-file Docker/.env -f Docker/compose.server.yml exec \
  -e VERDICT_DISABLE_WATCHER=1 server python manage.py createsuperuser
```

Log in at `/admin/`. Add an OpenBench **Profile** for the administrator, with
**Enabled** and **Approver** checked if the account will create/approve workloads.
A Django superuser does not automatically have a Verdict Profile. Normal users
can register at `/register/`; an administrator must enable their Profile before
they can contribute with a client.

### HTTPS reverse proxy

The image serves HTTP. For a proxy such as Caddy serving
`https://verdict.example.com`, set:

```dotenv
VERDICT_ALLOWED_HOSTS=verdict.example.com
VERDICT_CSRF_TRUSTED_ORIGINS=https://verdict.example.com
VERDICT_TRUST_PROXY=1
VERDICT_SECURE_COOKIES=1
```

Enable proxy trust only when the proxy overwrites `X-Forwarded-Proto` and is the
trusted route to the container. Leave secure cookies off for direct HTTP LAN
access. Deploy at the root of a dedicated hostname; these changes do not add
URL-prefix support.

[WhiteNoise](https://whitenoise.readthedocs.io/en/stable/django.html) serves
collected static assets with debug mode disabled. Uploaded files stay behind
Verdict's existing views, rather than a public media-directory mount.
[Gunicorn](https://gunicorn.org/reference/settings/) receives shutdown signals
directly. Compose allows 90 seconds for requests and the PGN watcher to finish.

### ZimaOS settings

Build or load `verdict-server:local` on the ZimaOS machine first. Use the supplied
server Compose file with Docker Compose, or configure the container with:

| Setting | Value |
| --- | --- |
| Image | `verdict-server:local` |
| Container port | `8000/tcp` |
| Host port | A free port, e.g. `8000` |
| Bind mount | Your persistent host directory → `/data`, read/write |
| Environment | `VERDICT_SECRET_KEY`, `VERDICT_ALLOWED_HOSTS`, plus proxy settings when applicable |
| Restart policy | `unless-stopped` |
| User | Image default `1000:1000` |
| Stop timeout | `90` seconds |

The server needs neither engine compilers nor privileged container access.
Configuration and catalogs are included in the image. For overrides, mount
individual files at `/app/Config/config.json`, `/app/Engines/<name>.json` or
`/app/Books/<name>.json`, then restart. Private-engine tokens can be mounted at
`/app/Config/credentials.<engine>`; credential files are excluded from the build
context. Do not mount an empty directory over the included configuration.

## Client setup

Set `USERNAME`, `PASSWORD` and `SERVER` in `Docker/.env`, then run:

```sh
docker compose --env-file Docker/.env -f Docker/compose.client.yml up -d --build
```

Use an enabled Verdict account. `SERVER` must be reachable from the client
container, e.g. `http://192.168.50.2:8000` or your HTTPS hostname. `localhost`
refers to the client container, not the server. The separate Compose files do
not assume a shared network; use the server's published address. No client port
mapping is needed.

The client retains LLVM 20, CMake, Ninja and Zig 0.15.2. The Zig download targets
**Linux x86-64**, so this client image is intended for amd64 hosts. Automatic
thread/socket allocation and hostname-based worker identity are preserved.
Named volumes retain engine, network and book caches. The server determines
the client version/ref for automatic downloads; this branch still advertises
`sync-with-upstream`.

## Validation without Docker

```sh
python -m pip install -r Docker/server-requirements.txt -r Client/requirements.txt
VERDICT_DISABLE_WATCHER=1 python manage.py test UnitTests --verbosity 2
```

The integration test launches the real server entrypoint and Gunicorn with a
temporary data directory, checks static serving with debug disabled, restarts
the server, and verifies database/media persistence and graceful shutdown. It
does not replace building and running both images with Docker.
