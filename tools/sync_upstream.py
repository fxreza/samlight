"""Refresh the pristine upstream snapshot on the `upstream` branch.

Downloads the current upstream source zip, replaces the tracked addon folder
with it, and commits - all inside a throwaway git worktree, so the branch you
are sitting on is never touched.

    python tools/sync_upstream.py

Exit code 0 = done (whether or not anything changed). Prints CHANGED=yes|no.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def addon_version(addon_xml_path):
    with open(addon_xml_path, "r", encoding="utf-8") as fh:
        head = fh.read(2000)
    m = re.search(r'<addon\b[^>]*\bversion="([^"]+)"', head)
    return m.group(1) if m else "unknown"


def ensure_vendor_branch():
    """Make sure a local `upstream` branch exists (CI starts with only main)."""
    branches = git("branch", "--list", config.VENDOR_BRANCH)
    if branches:
        return
    remote = git("ls-remote", "--heads", "origin", config.VENDOR_BRANCH, check=False)
    if remote:
        git("fetch", "origin", f"{config.VENDOR_BRANCH}:{config.VENDOR_BRANCH}")
    else:
        sys.exit(f"No `{config.VENDOR_BRANCH}` branch locally or on origin.")


def download_upstream(dest):
    print(f"Downloading {config.UPSTREAM_ZIP}")
    req = urllib.request.Request(
        config.UPSTREAM_ZIP, headers={"User-Agent": "samlight-sync"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        blob = resp.read()
    print(f"  {len(blob) / 1048576:.1f} MB")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(dest)
    top = os.path.join(dest, os.listdir(dest)[0])
    src = os.path.join(top, config.SOURCE_ID)
    if not os.path.isdir(src):
        sys.exit(f"Upstream zip has no {config.SOURCE_ID}/ folder.")
    return src


def main():
    ensure_vendor_branch()
    tmp = tempfile.mkdtemp(prefix="samlight-sync-")
    worktree = os.path.join(tmp, "wt")
    extract = os.path.join(tmp, "zip")
    os.makedirs(extract)
    try:
        new_src = download_upstream(extract)
        new_version = addon_version(os.path.join(new_src, "addon.xml"))

        git("worktree", "add", "--quiet", worktree, config.VENDOR_BRANCH)
        tracked = os.path.join(worktree, config.SOURCE_ID)
        old_version = (
            addon_version(os.path.join(tracked, "addon.xml"))
            if os.path.isdir(tracked)
            else "none"
        )

        if os.path.isdir(tracked):
            shutil.rmtree(tracked)
        shutil.copytree(new_src, tracked)

        git("add", "-A", config.SOURCE_ID, cwd=worktree)
        if not git("status", "--porcelain", cwd=worktree):
            print(f"Upstream unchanged (addon {old_version}).")
            print("CHANGED=no")
            return
        git(
            "commit",
            "--quiet",
            "-m",
            f"Upstream snapshot: {config.SOURCE_ID} {new_version} "
            f"({config.UPSTREAM_REPO} @ {config.UPSTREAM_BRANCH})",
            cwd=worktree,
        )
        print(f"Snapshot updated: {old_version} -> {new_version}")
        print("CHANGED=yes")
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", worktree],
            cwd=ROOT,
            capture_output=True,
        )
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
