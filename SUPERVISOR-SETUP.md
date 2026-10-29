# Supervisor extension for HA Codex 1.2.35

Maintained in `marvin6396/ha-codex` as `1.2.35-supervisor.1`. This is not an upstream release.
See [fork installation and updates](FORK-SETUP.md) for the selected installation path.
The running HA Codex container, its helper, developer instructions and
Home Assistant settings have not been changed by preparing this source tree.

## What changes

The add-on manifest requests `hassio_api: true` and `hassio_role: manager`.
The existing public helper gains `ha-codex-ha supervisor ...` commands.
The internal implementation is installed alongside it by the Dockerfile.

The new Configuration option `supervisor_access` has three values:

| Value | Helper capabilities |
| --- | --- |
| `off` | Supervisor commands disabled (default) |
| `read` | System/Core/OS/Supervisor/network/hardware information, installed apps, resource usage, logs, store, backups and jobs |
| `manage` | Read access plus app lifecycle/install/update/uninstall, option validation and saving, Core/OS/Supervisor updates, backup creation/restore/delete and host reboot/shutdown |

These are helper-level modes. Installing this manifest grants the container's
Supervisor token the manager role even when the helper is off or in read mode.
The modes do not revoke that role. Removing the permission requires installing
a manifest without it. Supervisor manager access lowers the add-on's Home
Assistant security rating. No host shell, Docker socket, protection-mode
changes, disk wipe or arbitrary API dispatcher is added. This is broad
Supervisor management, not unrestricted access to every host operation.

Existing Core checks, reloads and restarts keep their current settings and
configuration-check requirement. Core updates also run that same check first,
so they require `home_assistant_control: true`. The developer instructions
continue to require approval before reloads and restarts.

`addon-info` omits configuration options. `options-set` reads existing options
internally, replaces only supplied top-level keys, validates the combined
options, and saves only after a passing validation. A supplied nested object
replaces that complete object. Unspecified options and secret references are
preserved. JSON request bodies are passed to curl through stdin, not argv.
Logs may still contain secrets printed by the app itself; review them before
sharing. Failed validation details are not echoed because they can contain
the rejected secret value. Supervisor rejection/HTTP failure is an error, not
reported as a successful mutation.

## Build and installation paths

A normal restart of 1.2.35 cannot add manifest permissions. Editing the helper
inside the running container also cannot add Supervisor permissions and is not
the installation method.

The preferred way to preserve the current add-on identity and private data is
to have the maintainer include a reviewed change in a release of the existing
repository, then update through Home Assistant. For this personal fork, use
the separate repository and migration procedure in FORK-SETUP.md. This folder
includes the source and tests; no contribution to the original maintainer is
part of installing this fork.

An alternative is a user-owned fork or local add-on. A different repository or
local install normally gets a different add-on ID and private configuration
directory. It does not automatically inherit `/config/codex`, saved chats,
authentication, options, or the custom Codex Chats startup hook. Do not
uninstall the original add-on to switch to a fork. First create and download
a backup of HA Codex and Home Assistant, and plan migration of that private
data through a separately authorized administrator environment.

For a local build, an administrator with access to the Home Assistant `addons`
folder can copy `home_assistant_codex_app/` into an unused folder there, reload
the App Store and install the local app. Home Assistant builds from the
included Dockerfile and pinned build.yaml. Installing a fork uses its own
repository URL instead. Installation and any stop/restart are separate user
actions; they have not been performed here. Avoid running two Codex Chats
backends against the same socket or chat data at the same time.

After the candidate is installed and migration is ready:

1. Set `supervisor_access: read` in the new add-on configuration.
2. Restart that add-on and start a new Codex session so permissions and exported
   environment are refreshed. Any custom chat backend needs to inherit the new
   environment too; a separately installed startup hook must be reinstalled
   after an add-on image update if the upstream image does not contain it.
3. Run the read-only checks below. Verify authentication, chat history and
   the custom chat interface before retiring the original installation.
4. Change to `manage` and restart only after the read-only checks succeed.
   Review the proposed action before any operation with side effects.

## First read-only checks after installation

```sh
ha-codex-ha supervisor info system
ha-codex-ha supervisor info supervisor
ha-codex-ha supervisor addons
ha-codex-ha supervisor logs ADDON_SLUG 100
```

Use the actual Cloudflared slug from `addons`; do not assume its repository
prefix. `ha-codex-ha supervisor --help` lists the complete commands.

For option changes, place only changed top-level options in a private JSON
file, then use `options-validate SLUG FILE` and `options-set SLUG FILE`.
Restart is a separate explicit operation. Backups are asynchronous jobs;
successful submission is not proof that the backup or restore has finished.
Use `job JOB_ID` and the backup/add-on status to verify completion. A request
timeout can leave work running; inspect status before retrying.

## Validation

```sh
bash -n home_assistant_codex_app/ha-codex-ha
bash -n home_assistant_codex_app/ha-codex-supervisor
bash -n home_assistant_codex_app/run.sh
bash -n home_assistant_codex_app/session.sh
python3 -m unittest discover -s tests -v
```

The tests use a fake curl executable and a test-only token. They do not contact
the real Supervisor. The CI workflow also runs them before the amd64/aarch64
image build and existing startup smoke tests. Passing these checks verifies
the image and fixture-based startup, not authorization against a live
Supervisor. Verify live access separately after installation.

API references:

- https://contributors.home-assistant.io/apps/supervisor-api/
- https://contributors.home-assistant.io/apps/supervisor-api/apps/
- https://contributors.home-assistant.io/apps/supervisor-api/store/
- https://contributors.home-assistant.io/apps/supervisor-api/backups/
