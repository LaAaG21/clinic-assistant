# Deployment and rollback (#59)

This guide covers deploying a tagged release, or a release candidate, to an
Ubuntu VM in VirtualBox, and rolling it back without losing PostgreSQL data. It
extends the local setup guide from #47. The deployment uses the Compose `api`
service and `Dockerfile` from #25, the settings from #18, the health endpoint
from #14 and the smoke script from #54.

The API image is **built on the VM from the checked-out source**. Only the
public `python` and `postgres` base images are pulled. No application image is
pushed to or pulled from a registry. The schema comes only from `db/init/`, so
there is no SQL outside the repository. No assets are copied in by hand, and the
VM needs no Python or uv installation.

> **Prerequisite:** Use a revision that contains the `api` service in
> `compose.yaml`, which arrives with #25. Before #25 is merged, `docker compose
> up` starts only PostgreSQL. To check a revision, run
> `git show <revision>:compose.yaml | grep -q '^  api:' && echo ok`.

Every command below runs **inside the VM** from `~/clinic-assistant` unless the
step says otherwise.

## 1. Ubuntu VirtualBox prerequisites

| Item | Requirement |
| --- | --- |
| Hypervisor | VirtualBox 7, with hardware virtualisation enabled in the host's firmware. |
| Guest OS | Ubuntu Server 24.04 LTS (amd64), with OpenSSH server selected during install. |
| Resources | At least 2 vCPUs, 4 GB RAM and 25 GB disk. The API image is about 320 MB, and image builds need extra space. |
| Network | Adapter 1 set to NAT, with internet access to clone the repository and pull base images. |
| SSH | A NAT port-forwarding rule: host `127.0.0.1:2222` to guest port `22`. |
| Clock | NTP enabled (the Ubuntu default). Timestamps and backup names use UTC. |

Install Git, curl, OpenSSL and Docker Engine with the Compose plugin from
Docker's apt repository:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in so the group change takes effect. Then confirm that
`docker compose version` prints Compose v2 or newer, and that
`docker run --rm hello-world` succeeds.

Both published ports bind to `127.0.0.1` **inside the VM**, so VirtualBox port
forwarding cannot reach them. To open Swagger UI from the host, use an SSH
tunnel. Run this **on the host**:

```sh
ssh -p 2222 -L 8000:127.0.0.1:8000 <vm-user>@127.0.0.1
```

Then open `http://127.0.0.1:8000/docs` on the host.

## 2. Clone and select the revision

```sh
git clone https://github.com/LaAaG21/clinic-assistant.git ~/clinic-assistant
cd ~/clinic-assistant
git fetch --tags origin
git tag -l 'v*' --sort=-v:refname
```

To deploy a release, check out its tag in detached mode. Never deploy a moving
branch.

```sh
git switch --detach v0.1.0
git describe --tags --exact-match   # must print v0.1.0
```

To deploy a release candidate, use its full commit SHA from the pull request or
`main`, for example `git switch --detach 09550b7`. In both cases,
`git status --short` must print nothing. The image is built from this working
tree, so local edits would end up in the image.

## 3. Configure `.env`

```sh
cp .env.example .env
chmod 600 .env
PW=$(openssl rand -hex 24)   # URL-safe: letters and digits only
sed -i "s/change-me/$PW/g" .env
unset PW
```

Then edit `.env` with `nano .env`:

- Set `CLINIC_TIMEZONE` to the clinic's IANA timezone. `Asia/Dubai` is only an
  example.
- Keep `MODEL_BACKEND=fake` and leave `OPENAI_API_KEY` empty, unless the release
  notes require the real backend. Never commit a real key.
- Set `API_PORT` or `POSTGRES_PORT` only if 8000 or 5432 is already in use on
  the VM.

Do not print a resolved Compose configuration, because it contains the
password. `.env` is ignored by Git and excluded from the image by
`.dockerignore`.

**Keep the same `.env` across upgrades and rollbacks.** An existing database
volume keeps the user and password it was created with. If you change
`POSTGRES_USER`, `POSTGRES_PASSWORD` or `POSTGRES_DB` later, the API is locked
out, and the volume is not changed.

## 4. Start the release

```sh
docker compose config --quiet
docker compose up --build -d --wait
```

`--build` builds the API image from the checked-out source with
`uv sync --locked`. `--wait` returns only after both the database and API health
checks pass, and exits non-zero otherwise. On a fresh volume, PostgreSQL runs
`db/init/*.sql` in name order.

Record what is running. The rollback procedure uses this log:

```sh
echo "$(date -u +%FT%TZ) $(git rev-parse HEAD) $(git describe --tags --always)" >> ~/clinic-deployments.log
```

## 5. Verify health and smoke checks

```sh
docker compose ps                                   # both services (healthy)
curl --fail-with-body http://127.0.0.1:8000/health  # 200 {"status":"ok","api":"reachable","database":"reachable"}
curl --fail -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/openapi.json   # 200
docker compose exec -T api python -m clinic_assistant.smoke --base-url http://127.0.0.1:8000
echo "smoke exit: $?"
```

The smoke script runs inside the API container, using the image's own Python,
so the VM needs no Python setup. Exit code `0` means every check passed. See
[smoke checks](smoke.md) for details. Until #44 adds `POST /conversations`, the
expected result is `PASS health`, then two `FAIL` lines and exit code `1`.
Revisions from before #54 do not contain the smoke module. For those, rely on
the `curl` checks.

If `--wait` fails, run `docker compose logs api --tail 50`. A configuration
error exits before Uvicorn starts and names the field without echoing its
value.

## 6. Back up before every change

Always take a backup before an upgrade or rollback, while the current revision
is still running:

```sh
mkdir -p ~/clinic-backups
BACKUP=~/clinic-backups/clinic-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ).dump
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$BACKUP"
docker compose exec -T db pg_restore --list < "$BACKUP" > /dev/null && echo "backup readable: $BACKUP"
```

The revision in the file name tells you which schema the dump belongs to. Keep
backups outside the repository directory and copy them off the VM.

## 7. Check schema compatibility

The files in `db/init/` run **only when the volume is first created**. Changing
the checked-out code never changes the schema of an existing database.
Compatibility must therefore be checked explicitly in both directions. Set
`TARGET` to the revision you are moving to, then run:

```sh
TARGET=v0.1.0
git cat-file -e "$TARGET^{commit}" && echo "target exists"
git diff --name-status "$TARGET" HEAD -- db/init
```

| Diff output | Meaning |
| --- | --- |
| Nothing | Same schema. Compatible in both directions. |
| Only `A` lines (rolling **back**) | The live database has extra tables that the target never uses. Compatible. Leave those tables in place; their data is kept for the next roll-forward. |
| Only `A` lines (rolling **forward**, with `HEAD` and `TARGET` swapped) | The target needs new tables. Apply each added file once, in name order, before you start the new API (see [local PostgreSQL](database.md)). |
| Any `M`, `D` or `R` line | An existing table changed. **Not compatible.** Do not deploy over this volume. Restore a backup that matches the target (section 9), or write a reviewed migration. |

Then confirm that every table the target expects exists in the live database:

```sh
git grep -hoE '^CREATE TABLE [a-z_]+' "$TARGET" -- db/init | awk '{print $3}' | sort > /tmp/expected-tables
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select tablename from pg_tables where schemaname = '\''public'\''"' | sort > /tmp/live-tables
comm -23 /tmp/expected-tables /tmp/live-tables   # must print nothing
```

## 8. Roll back to a known-good revision

1. **Choose a real target.** Pick a release tag (`git tag -l 'v*'`) or the
   previous line in `~/clinic-deployments.log` that passed section 5. It must be
   a published tag, or a commit on `origin` (`git branch -r --contains "$TARGET"`
   prints at least one branch), and it must include the `api` service (see the
   prerequisite at the top). Never roll back to an unpushed or unverified local
   commit.
2. **Back up** the current database (section 6).
3. **Check the schema** (section 7). Continue only if the result is compatible.
4. **Switch and rebuild, keeping the volume:**

   ```sh
   git switch --detach "$TARGET"
   git status --short   # must print nothing
   docker compose up --build -d --wait
   ```

   Compose recreates the `api` container from the target's source. The `db`
   container and the `postgres-data` volume are reused.
5. **Verify** with section 5, then add a line to `~/clinic-deployments.log` as
   in section 4.

To roll forward again, follow the same steps with the newer revision as
`TARGET`.

**Never run these during a rollback.** They delete the database:
`docker compose down -v`, `docker volume rm <project>_postgres-data` and
`docker system prune --volumes`. Plain `docker compose down` and `up` are safe,
because the named volume survives. See
[why the data survives](database.md#why-the-data-survives).

### Restoring v0.1.0

Use section 8 with `TARGET=v0.1.0`. The schema change policy is additive: each
change is a new numbered file in `db/init/`. As long as that holds, section 7
reports only `A` lines, and you can roll back without touching data.

## 9. Restore a backup when the schema is incompatible

Use this only when section 7 reports `M`, `D` or `R` lines, or a missing table.
Pick a backup whose file name contains the **target** revision. The live
database is renamed, not dropped, so no data is lost.

```sh
RESTORE=~/clinic-backups/<dump taken while the target was running>.dump
docker compose stop api
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > ~/clinic-backups/before-restore-$(date -u +%Y%m%dT%H%M%SZ).dump
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists clinic_restore && createdb -U "$POSTGRES_USER" clinic_restore'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d clinic_restore --no-owner --exit-on-error' < "$RESTORE"
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -c "ALTER DATABASE \"$POSTGRES_DB\" RENAME TO \"${POSTGRES_DB}_before_restore\"" -c "ALTER DATABASE clinic_restore RENAME TO \"$POSTGRES_DB\""'
git switch --detach "$TARGET"
docker compose up --build -d --wait
```

Then verify with section 5. The renamed database `<db>_before_restore` keeps
everything that was written after the backup was taken. Drop it only after the
team agrees that its data is not needed.

## Verification record (2026-11-09)

The candidate was a fresh clone of `main` (`09550b7`), merged locally with the
unmerged #25 branch (`cef60a2`), giving local commit `2a051d2`. It was checked
on Windows 11 with Docker 29.9.1 and Compose v5.6.0, under the isolated project
`clinic-issue59`. The environment used synthetic credentials from
`openssl rand -hex 24`, fake model mode and host ports 18059 and 55459.

| Step | Observed result |
| --- | --- |
| `config --quiet`, `up --build -d --wait` | Passed in 34 s. The API image was built from source; both services were healthy. |
| `GET /health` | HTTP 200, `{"status":"ok","api":"reachable","database":"reachable"}`, `Cache-Control: no-store`. |
| Smoke check inside the `api` container | `PASS health`, `FAIL openapi`, `FAIL create-conversation`, exit `1`. This matches the documented pre-#44 result. |
| Fresh-volume schema | `bookings`, `conversations`, `doctors`, `requests`, `slots`, created without manual SQL. |
| Backup (section 6) | A custom-format dump with one synthetic doctor row. `pg_restore --list` read it successfully. |
| Schema check `cef60a2` → `2a051d2` | `A db/init/004_requests.sql` only. All expected tables were present (`comm` printed nothing). |
| Rollback to `cef60a2` (section 8) | The API was rebuilt and healthy. The same volume was kept (unchanged creation time), and the synthetic row was still present. The extra `requests` table was left in place. The smoke module was absent in that revision (`ModuleNotFoundError`), so `curl` was used, as documented. |
| Roll forward to `2a051d2` | Healthy. `PASS health`, and the synthetic row was still present. |
| Backup restore (section 9 commands) | The dump was restored into `clinic_restore`, and the databases were swapped by rename. The restored database held only the backed-up row; `clinic_before_restore` kept both rows. |

All `clinic-issue59` containers, images and volumes were removed afterwards
(`down -v --rmi local`).

**Not verified here (left for #84 and #89):**

- Running the procedure inside an Ubuntu 24.04 VirtualBox VM. Section 1 has not
  been run.
- The `v0.1.0` tag, which does not exist yet, so its rollback has not been
  exercised.
- A fully passing smoke run, which needs #44.
- A deployment of a merged `main` that includes #25.

## Learning question

*Why must rollback compatibility include the database schema as well as
application code?* The application code and the data live in different places.
`git switch` and `up --build` replace the container, but the `postgres-data`
volume, and the schema inside it, stays exactly as the newer release left it,
because `db/init/` never runs again on an existing volume. Older code is safe
only if every table and column it reads and writes still exists with the shape
it expects. Extra tables are harmless, but a changed or removed column breaks
the older code at runtime, even though its own image is perfectly healthy.
Restoring an old backup instead would silently discard every record written
since. Checking the schema before switching code is what makes a rollback both
working and data-safe.
