# Marvin's HA Codex Supervisor fork

Repository: https://github.com/marvin6396/ha-codex

This fork adds Supervisor management to upstream HA Codex. The helper modes,
available commands and permission boundaries are documented in
[SUPERVISOR-SETUP.md](SUPERVISOR-SETUP.md). This is a separate add-on installation
with its own repository prefix and private configuration directory.

## Install after checks pass

1. Create and download a backup including the existing HA Codex add-on and Home
   Assistant configuration. Keep the original add-on installed.
2. Add `https://github.com/marvin6396/ha-codex` to the Home Assistant App Store's
   repositories.
3. Install **HA Codex Supervisor** from **Marvin HA Codex Supervisor**. It builds
   from the included Dockerfile. Its settings and private `/config/codex` do not
   automatically come from the original installation.
4. Migrate the old add-on's private Codex directory, authentication, options and
   custom chat startup hook through an authorized administrator environment.
   Do not publish or commit those private files. The existing chat UI's backend
   and watchdog must not run in two containers against the same data/socket.
5. Configure `supervisor_access: read`, then start/restart the candidate only
   with the user's approval. Start a fresh Codex session in that add-on.
6. Verify authentication/history and the read-only checks in
   SUPERVISOR-SETUP.md. Only then enable `manage` and retire the original runtime.

Installing this build grants its container the Supervisor manager role even
while the helper mode is off. No host shell or Docker socket is provided.

## Original-project updates

The `ha-codex-ha cloud-remote disconnect` command disables only Nabu Casa's
remote UI tunnel; `cloud-remote connect` provides the reverse operation. Both
require `home_assistant_control: true` and `supervisor_access: manage`. They do
not log out of Nabu Casa or disable Alexa/Google account linking. When changing
the remote URL, verify the replacement HTTPS entry point first and account for
the current browser/app session disconnecting when its old tunnel is disabled.

Version `1.2.35-supervisor.2` also starts the existing custom Codex Chats watchdog
when its integration file is present. For this fork's updates, the startup hook
no longer needs to be reapplied manually. Other distributions may still need
their separate hook installer.

**Review upstream HA Codex updates** checks the latest published upstream
release daily at 07:41 UTC and can also be started under Actions → Run workflow.

- Already integrated releases do nothing.
- A newer release is merged into an isolated `upstream-sync/vX.Y.Z` branch.
- Version-only conflicts and distinct new scalar option/schema keys can be
  combined. Other conflicts fail visibly in Actions; they never overwrite fork
  changes or main. Such updates need a manual merge.
- The fork version becomes `X.Y.Z-supervisor.1`. Fork notes live separately in
  FORK-CHANGELOG.md so the upstream release notes do not conflict on each update.
- Tests run before the proposal is pushed. A draft pull request is opened, then
  amd64/aarch64 image builds and startup smoke tests run. A passing proposal is
  marked ready for your review; failed builds leave it as a draft.
- Review and merge the proposal yourself. The workflow never merges or deploys
  automatically. A closed proposal is respected and not recreated each day.
- After merging, refresh Home Assistant's App Store/update information. The
  higher version in the fork's manifest is the update source; publishing a
  GitHub Release is not required. Inspect the change before installing it.
- If an image update replaces a custom Codex Chats start hook, reinstall that
  hook before relying on the custom chat UI.

The inherited **Update Codex CLI** and **Publish HA Codex release** workflows
are guarded to run only in the original repository. This fork follows published
upstream add-on releases rather than creating an independent CLI release stream.

## GitHub Actions setup

Enable Actions in the fork. Under Settings → Actions → General → Workflow
permissions, allow GitHub Actions to create pull requests. Workflow-level
permissions grant only the contents/actions/pull-request writes needed here;
the default token permission can remain read-only.

GitHub may disable scheduled workflows after 60 days without repository
activity. If updates stop appearing, check the Actions page and re-enable the
workflow. Manual conflict resolution and reviewing update proposals remain
part of maintaining a fork.

## Fork-only fixes

For another release based on the same upstream version, increment the trailing
fork revision, for example `1.2.35-supervisor.1` → `1.2.35-supervisor.2`, add notes
to FORK-CHANGELOG.md and run the validation workflow before merging. Do not use
GitHub's discard-changes sync option, because that removes the extension.
