# Verdict upstream sync

This branch starts at OpenBench `e8f36d5f3b24fd2ac28787117bf3ee888b65f309`
and reapplies Verdict's changes from `master` at
`a88f102210e058945c29846c79b027faa49bb989`. The actual common ancestor is
`993dad175b028c5ffcd01919e491c9ad98e29cce`; differences caused only by newer
upstream development are not Verdict customizations.

## What was reapplied

| Area | Behavior on this branch |
| --- | --- |
| Engine catalog | StockDory, Pawnocchio and Stash, with Verdict's compiler requirements and NPS values: 2,000,000; 1,000,000; and 1,615,000 respectively. |
| Presets | Verdict's time controls, hashes, adjudication settings, SPRT bounds, fixed-game limits and SMP presets. Throughput balancing remains enabled. |
| Opening books | The shared `UHO_Lichess_4852_v1.epd` book, with the current upstream checksum and source. The unused catalog entries are removed as on Verdict master. |
| Branding | Verdict page title and header, README attribution, account error wording, email-first forms and explicit password confirmation labels. Upstream's support links and Ethereal sales page are removed. |
| SPRT summaries | LLR first, Elo and its 95% interval second, then game counts and optional pentanomial counts. |
| Docker | Ubuntu 24.04, LLVM 20, CMake, Ninja and Zig 0.15.2, with Verdict's CPU allocation policy and worker identity. |
| Developer setup | Verdict's existing IDE files and TOML ignore rule. Upstream's tracked migrations remain tracked. |

## Compatibility adjustments

- Keep client/server protocol **50** and the Fastchess configuration from
  upstream. Do not copy the old version 37 worker or Cutechess binaries.
- The client download source is Verdict's **`sync-with-upstream`** branch.
  The Docker build defaults to the same branch. Using `master` here would
  download the incompatible old client.
- Discover the `Client` directory inside GitHub archives instead of assuming
  an `OpenBench-<ref>` directory. Missing worker files now raise an error
  instead of silently completing an update without copying anything.
- Pawnocchio's tuning book now uses the configured shared book instead of
  the missing `UHO_4060_v2.epd`. Its LTC tuning control is corrected from
  `60+0.0.6` to `60+0.6`.
- Docker always assigns at least one thread, with a valid socket count even
  on small hosts or restricted CPU sets. `SERVER` can target a staging server;
  it defaults to Verdict's existing server URL.
- Retain upstream's fresh machine registration per worker session. Caching
  `machine.txt` was inherited behavior removed by upstream, not a Verdict
  customization. Likewise, retain the current archive NPS tools, network
  deletion API, template behavior, SPSA models and NPS accounting.

## Validation

From a Python environment containing the server and client requirements:

```sh
python -m pip install -r requirements.txt -r Client/requirements.txt
python manage.py migrate --noinput
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test UnitTests --verbosity 2
bash -n Docker/run.sh
```

Run these in a disposable checkout/database. The inherited app startup hook
starts a PGN watcher even for management commands; on an empty database it can
log a missing-table exception before the first migration creates its table.

The regression suite covers fork/upstream/commit archive names, incomplete
archives, client bootstrap preservation, preset books and time controls,
matching client/server versions, SPRT summaries, public and authenticated
forms, client configuration endpoints, Docker CPU allocation, and an upgrade
from `0001_initial` with populated tuning/results records and legacy engine
URLs. The old Verdict master model fields were also compared with upstream's
`0001_initial` and matched, including defaults and relationships.

The Docker entrypoint is tested with simulated CPU topologies. A complete
Docker image build and live engine matches still need an environment with
Docker and suitable worker hardware.

## Trying the worker image

From the repository root:

```sh
docker build --build-arg VERDICT_REF=sync-with-upstream -t verdict:sync Docker
docker run --rm -e USERNAME -e PASSWORD -e SERVER verdict:sync
```

Export `USERNAME`, `PASSWORD` and the staging server's `SERVER` URL first.
The server must run this branch too. Existing workers need their **bootstrap
`Client/client.py` refreshed**, not just an automatic worker update: the old
bootstrap contains the repository-name assumption and deliberately never
updates itself. A fresh clone of this branch or rebuilt image supplies it.

## Upgrading an existing Verdict database

No production database or running worker was changed by preparing this branch.
Before deployment, stop the old server and workers and back up the database,
`Media`, and local settings/credentials together. Rehearse on a copy first.

Old Verdict does not track its locally generated migration files. Preserve
those files for comparison and inspect the deployed migration history and
schema before using the new migration chain. The old master model schema
matches upstream's initial migration, but that does not establish what local
migrations have actually run on a deployed database.

- If the old schema is present and `OpenBench.0001_initial` is already recorded,
  apply the remaining migrations normally with `python manage.py migrate`.
- If the old schema is present but that initial migration is not recorded,
  verify the schema first, then use `python manage.py migrate --fake-initial`
  on the copy. Django's initial-migration detection checks table presence,
  not full schema equality.
- If the deployed schema or locally generated migration history differs,
  reconcile it before proceeding. Do not fake all migrations or delete the
  database/migration history to silence an error.

The new chain converts SPSA JSON to relational records, removes old fields,
normalizes engine source URLs and adds NPS counters. Validate existing tests,
tunes, networks and PGN downloads on the upgraded copy before deployment.
For rollback, restore the pre-upgrade database and files with the old code;
reversing these data migrations is not a substitute for that backup.

## Eventual promotion

The branch is a clean descendant of current upstream. No merge or ancestry
rewrite of Verdict's `master` is included. Before promoting it, choose the
long-term client download ref and update **both** `Config/config.json` and
Docker's `VERDICT_REF` default together (and the branch-specific regression
assertions). Keep the download ref available while any server advertises it.
