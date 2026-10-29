#!/usr/bin/env python3
"""Prepare a review branch by merging an upstream release; never push/force-reset.

Version-only conflicts and independent scalar-key additions in config.yaml
are resolved automatically. Other conflicts abort, preserving both sides.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

CONFIG = "home_assistant_codex_app/config.yaml"
VERSION = re.compile(r'^version: "[^"\n]+"$', re.MULTILINE)
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
PLACEHOLDER = 'version: "SYNC_VERSION_PLACEHOLDER"'


def git(repo, *args, check=True, **kwargs):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          text=True, capture_output=True, **kwargs)


def normalized_config(text):
    result, count = VERSION.subn(PLACEHOLDER, text)
    if count != 1:
        raise ValueError("Expected one quoted top-level version in config.yaml")
    return result


def independent_additions(text):
    """Join pure insertions of distinct one-line mapping keys, never edits."""
    conflict = re.compile(r"^<<<<<<< [^\n]*\n(.*?)^\|\|\|\|\|\|\| [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n",
                          re.MULTILINE | re.DOTALL)

    def resolve(match):
        ours, base, theirs = match.groups()
        if base.strip():
            raise RuntimeError("config.yaml has a conflict beyond its version; manual merge required")
        groups = []
        for side in (ours, theirs):
            keys = []
            for line in side.splitlines():
                if not line.strip():
                    continue
                key = re.fullmatch(r"( +)([A-Za-z0-9_]+):\s*(.+)", line)
                if not key or key[3].strip() in ("|", ">", "|-", ">-", "|+", ">+"):
                    raise RuntimeError("config.yaml has a conflict beyond its version; manual merge required")
                keys.append((len(key[1]), key[2]))
            groups.append(keys)
        keys = groups[0] + groups[1]
        if not groups[0] or not groups[1] or len({key[0] for key in keys}) != 1 or len(set(keys)) != len(keys):
            raise RuntimeError("config.yaml has a conflict beyond its version; manual merge required")
        return ours + theirs

    merged = conflict.sub(resolve, text)
    if any(line.startswith(("<<<<<<< ", "||||||| ", "=======", ">>>>>>> ")) for line in merged.splitlines()):
        raise RuntimeError("Unresolved config.yaml merge conflict")
    return merged


def resolve_version_conflict(repo):
    with tempfile.TemporaryDirectory() as temp:
        paths = []
        # merge-file expects ours, base, theirs.
        for name, stage in (("ours", 2), ("base", 1), ("theirs", 3)):
            data = git(repo, "show", f":{stage}:{CONFIG}").stdout
            path = Path(temp) / name
            path.write_text(normalized_config(data))
            paths.append(str(path))
        merged = subprocess.run(["git", "merge-file", "--diff3", "-p", *paths],
                                text=True, capture_output=True)
        if merged.returncode < 0 or merged.returncode > 127:
            raise RuntimeError("config.yaml has a conflict beyond its version; manual merge required")
        return independent_additions(merged.stdout)


def prepare(repo, tag):
    repo = Path(repo)
    if not TAG.fullmatch(tag):
        raise ValueError("Expected an upstream release tag vX.Y.Z")
    if git(repo, "status", "--porcelain").stdout.strip():
        raise RuntimeError("Refusing to merge into a dirty worktree")
    if git(repo, "branch", "--show-current").stdout.strip() != "main":
        raise RuntimeError("Start from the fork's main branch")
    git(repo, "fetch", "--no-tags", "upstream", f"refs/tags/{tag}")
    upstream = git(repo, "rev-parse", "FETCH_HEAD^{commit}").stdout.strip()
    if git(repo, "merge-base", "--is-ancestor", upstream, "HEAD", check=False).returncode == 0:
        return {"update": "false"}
    upstream_config = git(repo, "show", f"{upstream}:{CONFIG}").stdout
    if f'version: "{tag[1:]}"' not in upstream_config.splitlines():
        raise RuntimeError("Release tag does not match upstream's add-on version")
    branch = f"upstream-sync/{tag}"
    original = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "switch", "-c", branch)
    merged = git(repo, "merge", "--no-commit", "--no-ff", upstream, check=False)
    try:
        conflicts = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
        if conflicts:
            if conflicts != [CONFIG]:
                raise RuntimeError("Manual merge required for: " + ", ".join(conflicts))
            config = resolve_version_conflict(repo)
        elif merged.returncode:
            raise RuntimeError("Upstream merge failed: " + merged.stderr.strip())
        else:
            config = normalized_config((repo / CONFIG).read_text())
        fork_version = f"{tag[1:]}-supervisor.1"
        config = config.replace(PLACEHOLDER, f'version: "{fork_version}"')
        # Do not prepare a candidate if the defining fork capabilities vanished.
        for line in ("hassio_api: true", "hassio_role: manager",
                     "  supervisor_access: list(off|read|manage)",
                     "url: https://github.com/marvin6396/ha-codex"):
            if line not in config.splitlines():
                raise RuntimeError("Required fork configuration missing: " + line)
        (repo / CONFIG).write_text(config)
        changelog = repo / "FORK-CHANGELOG.md"
        entry = (f"## {fork_version}\n\n"
                 f"- Merged upstream release {tag}, preserving the Supervisor extension.\n"
                 "- Requires passing helper tests and both architecture builds before use.\n\n")
        old = changelog.read_text() if changelog.exists() else ""
        changelog.write_text(entry + old)
        git(repo, "add", CONFIG, "FORK-CHANGELOG.md")
        git(repo, "commit", "-m", f"Merge upstream {tag} into Supervisor fork")
    except Exception:
        if git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode == 0:
            git(repo, "merge", "--abort")
        git(repo, "switch", "main")
        # No force/reset, including on failure. Clean merge abort restores main.
        if git(repo, "rev-parse", "HEAD").stdout.strip() != original:
            raise RuntimeError("Unexpected change to main")
        raise
    return {"update": "true", "branch": branch, "sha": git(repo, "rev-parse", "HEAD").stdout.strip(),
            "version": fork_version}


if __name__ == "__main__":
    result = prepare(Path.cwd(), sys.argv[1])
    for key, value in result.items():
        print(f"{key}={value}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as stream:
            stream.writelines(f"{key}={value}\n" for key, value in result.items())
