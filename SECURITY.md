# Secure deployment and migration

## Boundary and defaults

This stack is local-only by default. Every published port binds to `127.0.0.1`:
Langfuse `3000`, the inference API `8000`, and OpenWebUI `8080`. Services still
communicate on the private Docker network. Docker-host users and containers on
that network are inside this trust boundary. Use a supported, patched Docker
Engine (28+ for the localhost-publishing isolation fixes).

OpenWebUI authentication is **always enabled** in the supplied Compose files.
`ENABLE_SIGNUP=false` and Langfuse `AUTH_DISABLE_SIGNUP=true` close registration
by default. A `.env` entry cannot override a literal Compose setting. The two
signup switches are interpolated explicitly; `WEBUI_AUTH` is not an opt-out.

vLLM and SGLang require `VLLM_API_KEY` (the name is retained for compatibility).
OpenWebUI uses the same key for its internal backend connection. Engine API
keys cover selected API routes, not every administrative/health endpoint;
loopback isolation remains required even when a key is configured. TensorRT-LLM
has no API authentication wired in this stack: its API is loopback-only, and
must stay behind an authenticated proxy if remote access is required. The key
sent by OpenWebUI does not add authentication to TensorRT-LLM.

Do not change port bindings to `0.0.0.0` for convenience. Prefer SSH forwarding
from an authorized client, for example `ssh -L 8080:127.0.0.1:8080 server`.
A shared remote deployment needs separately reviewed TLS, authentication,
network policy and reverse-proxy configuration. Docker port publication can
bypass host firewall rules. Do not rely on a firewall setting alone.

## New installation only

1. On a trusted host, run `python3 scripts/configure_env.py --init`.
   This exclusively creates a mode-0600 `.env` with independent random secrets.
   It refuses to overwrite any existing path. Keep a secure backup, particularly
   `ENCRYPTION_KEY` and `SALT`. Never run initialization to repair a missing
   configuration for existing data. Restore the original configuration instead.
2. Set `HF_TOKEN` if required by the chosen model. Literal `KEY=value` entries
   and simple quoted values are supported; expansion, escapes, inline comments,
   duplicate keys and multiline values are rejected. Required service secrets
   use at least 32 URL-safe characters (`A-Z`, `a-z`, digits, `_`, `-`, `.`).
   `ENCRYPTION_KEY` is exactly 64 hexadecimal characters. This avoids unsafe
   interpolation and PostgreSQL URL-encoding ambiguity.
3. During supervised first-user setup only, set `ENABLE_SIGNUP=true` and
   `AUTH_DISABLE_SIGNUP=false` in `.env`. Keep all ports loopback-only. Start
   with `./run.sh vllm` (or the selected engine). Create your own OpenWebUI
   administrator and Langfuse user/project through the local UIs or an SSH
   tunnel. There is no bundled account or shared default password.
4. Immediately disable signup in the **OpenWebUI Admin UI** as well as setting
   `ENABLE_SIGNUP=false` and `AUTH_DISABLE_SIGNUP=true` in `.env`. OpenWebUI
   persists signup configuration in its database; changing `.env` alone may
   leave registration enabled after first boot.
   Set the Langfuse project API keys if tracing is desired. Re-run `./run.sh
   vllm` to validate, refresh the derived tracing header and recreate changed
   containers. **`docker compose restart` does not apply environment changes.**
5. Verify login is required, registration is closed, and `docker ps` shows only
   loopback host bindings. Check the effective configuration locally with
   `docker compose -f docker-compose.vllm.yml config --quiet`; avoid sharing
   unredacted `config`, `inspect`, environment output or logs, which can contain
   secrets and user data. Confirm a `/v1/models` call without a key is rejected for
   vLLM/SGLang. Inspect that result only on your own authorized deployment.

`./run.sh` validates configuration **before** installation, model downloads or
container changes. It does not initialize secrets, rotate passwords, reset data,
or silently repair legacy configuration. The validator considers exported shell
variables too, because Compose gives them precedence. Unset stale exported values
before changing `.env`. Required Compose substitutions independently reject blank
secrets, including when Compose is invoked directly. Use the startup validator for
placeholder, strength, uniqueness and migration checks.

## Existing deployments: deliberate migration

Do not deploy this update blindly. Schedule a maintenance window and back up
volumes plus the original private `.env`. Do not delete volumes or run `down -v`.
Keep existing encryption keys and salts: replacing them can make stored data or
credentials unusable. A loss of those keys requires a recovery plan, not automatic
regeneration.

- Check actual bindings, reverse proxies, users and configuration first. Restrict
  access to the services while migrating. Repository changes do not alter an
  already running deployment.
- If a public initial Langfuse password was used, change the **actual account
  password** through the existing administrative workflow. Review users/sessions
  and any affected project keys. Changing `LANGFUSE_INIT_USER_PASSWORD` does not
  change an existing account. After completing the account review, remove the
  legacy `LANGFUSE_INIT_USER_*` entries from `.env`; they are no longer passed to
  the service, and the validator blocks them to require this deliberate step.
- PostgreSQL, ClickHouse and MinIO now require `POSTGRES_PASSWORD`,
  `CLICKHOUSE_PASSWORD` and `MINIO_ROOT_PASSWORD`. Migrate each persistent
  service's **actual credential** and corresponding clients coherently before
  starting the new configuration. In particular, `POSTGRES_PASSWORD` only
  initializes an empty database and will not rotate an existing database user.
  Record matching strong values in `.env`. Do not just generate replacements and
  expect old volumes to accept them. Redis and application credentials must also
  match their clients. Rotate exposed credentials as a separate authorized task.
- Preserve already valid `ENCRYPTION_KEY`/`SALT`. If they were placeholders or
  weak defaults, the validator stops startup: plan the application's supported
  data/key migration rather than bypassing the check or replacing keys in place.
- OpenWebUI's existing volume can retain signup settings. Verify and close signup
  in its Admin UI as well as `.env`. Do not erase its database to enable auth.
  A previous no-auth installation needs an explicit account/migration review
  using the installed OpenWebUI version. Keep it isolated until login is verified.
- Add the inference API key to authorized clients. SGLang now uses the same
  `VLLM_API_KEY` name; TensorRT-LLM still relies on the network/proxy boundary.
- Run `python3 scripts/configure_env.py --check`, then use the selected engine's
  startup command during the approved maintenance window. Verify actual state
  afterward. Keep the original `.env` and backups until the migration is accepted.

The security helper only refreshes the derived OTEL header in `--prepare` mode;
it removes a stale header if both project keys are cleared. It never prints it.
The diagnostics script prints health/status, not credentials, trace payloads or
raw logs. `.env` and temporary `.env.*` files are ignored by Git.

## Verification without starting services

```bash
python3 -m unittest discover -s tests -v
bash -n run.sh scripts/diagnose_langfuse.sh
# Optional actual Compose rendering tests, no daemon or GPU required:
COMPOSE_BIN=/path/to/docker-compose python3 -m unittest discover -s tests -v
```

The tests use disposable temporary configurations and never contact a deployed
service. GPU inference, first-user setup, persisted-data migration, TLS and real
network isolation must be verified in an authorized deployment before rollout.

References: [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/),
[OpenWebUI authentication](https://docs.openwebui.com/reference/env-configuration/#webui_auth),
[Langfuse hardening](https://langfuse.com/self-hosting/configuration/hardening).
