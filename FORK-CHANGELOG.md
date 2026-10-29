## 1.2.35-supervisor.1

- Added Supervisor manager API access through `ha-codex-ha supervisor` with off/read/manage helper modes.
- Added add-on/system diagnostics, bounded logs, validated option changes, lifecycle actions, updates, backups and job status.
- Added a daily/manual upstream-release review workflow. Update candidates preserve fork changes, run tests and both image builds, and remain pull requests for manual review.
- Kept the original Codex auto-release workflows inactive in this fork; upstream's changelog and release history stay separate.
- Source is based on upstream v1.2.35. Live Supervisor validation and migration remain separate installation steps.
