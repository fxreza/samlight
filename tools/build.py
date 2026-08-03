"""Build the Kodi repository that GitHub Pages serves.

Takes the working tree's `plugin.video.redlight/` folder (upstream code plus
whatever you changed), rewrites the addon id to `plugin.video.samlight`, zips
it, zips the repository addon, and regenerates addons.xml + addons.xml.md5
under docs/.

    python tools/build.py

The rewrite happens at build time on purpose: the repo keeps upstream's folder
name and ids, so `git merge upstream` stays a clean text merge, and any new
file upstream adds is renamed automatically.

Prints BUILT=yes|no. A new version number is only minted when the built
content actually changed.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, config.DOCS_DIR)
STATE_FILE = os.path.join(DOCS, "build-state.json")

# Files we never ship.
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_EXT = {".pyc", ".pyo"}
# Binary assets are copied byte-for-byte, never string-rewritten.
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".zip", ".ttf", ".otf"}

ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed, so identical content -> identical zip


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def collect(src_dir):
    """Return {relpath: bytes} for everything we ship, ids already rewritten."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXT:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, src_dir).replace("\\", "/")
            data = read(full)
            if ext not in BINARY_EXT:
                data = data.replace(
                    config.SOURCE_ID.encode(), config.TARGET_ID.encode()
                )
            out[rel] = data
    return out


def rewrite_addon_xml(data, version):
    """Set id / name / provider-name / version on the root <addon> element."""
    text = data.decode("utf-8")
    m = re.search(r"<addon\b[^>]*>", text)
    if not m:
        sys.exit("addon.xml has no <addon> element.")
    tag = m.group(0)

    def attr(t, key, value):
        if re.search(rf'\b{key}="[^"]*"', t):
            return re.sub(rf'\b{key}="[^"]*"', f'{key}="{value}"', t, count=1)
        return t[:-1].rstrip() + f' {key}="{value}"' + t[-1]

    tag = attr(tag, "id", config.TARGET_ID)
    tag = attr(tag, "name", config.TARGET_NAME)
    tag = attr(tag, "provider-name", config.TARGET_PROVIDER)
    tag = attr(tag, "version", version)
    return (text[: m.start()] + tag + text[m.end():]).encode("utf-8")


def upstream_version(src_dir):
    m = re.search(
        r'<addon\b[^>]*\bversion="([^"]+)"',
        read(os.path.join(src_dir, "addon.xml")).decode("utf-8"),
    )
    if not m:
        sys.exit("Could not read upstream version from addon.xml.")
    return m.group(1)


def content_hash(files):
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode())
        h.update(hashlib.sha256(files[rel]).digest())
    return h.hexdigest()


def next_version(base, previous):
    """base 2.1.7 + previous 2.1.7.3 -> 2.1.7.4; new base -> 2.1.7.1"""
    if previous and previous.startswith(base + "."):
        tail = previous[len(base) + 1:]
        if tail.isdigit():
            return f"{base}.{int(tail) + 1}"
    return f"{base}.1"


def make_zip(addon_id, version, files):
    path = os.path.join(DOCS, addon_id, f"{addon_id}-{version}.zip")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(files):
            info = zipfile.ZipInfo(f"{addon_id}/{rel}", date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[rel])
    return path


def prune(addon_id, keep_name):
    d = os.path.join(DOCS, addon_id)
    zips = sorted(
        (f for f in os.listdir(d) if f.endswith(".zip")),
        key=lambda f: os.path.getmtime(os.path.join(d, f)),
        reverse=True,
    )
    for old in zips[config.KEEP_ZIPS:]:
        if old != keep_name:
            os.remove(os.path.join(d, old))


def strip_decl(text):
    return re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text).strip()


def main():
    state = {}
    if os.path.exists(STATE_FILE):
        state = json.loads(read(STATE_FILE).decode("utf-8"))

    built = False
    addon_xmls = []

    # --- the video addon ---------------------------------------------------
    src = os.path.join(ROOT, config.SOURCE_ID)
    files = collect(src)
    base = upstream_version(src)
    prev = state.get(config.TARGET_ID, {})
    version = prev.get("version") or f"{base}.1"
    # Hash without addon.xml's version attribute, so the hash reflects code only.
    probe = dict(files)
    probe["addon.xml"] = rewrite_addon_xml(probe["addon.xml"], "0")
    digest = content_hash(probe)

    if digest != prev.get("hash") or not prev.get("version"):
        version = next_version(base, prev.get("version"))
        built = True
    files["addon.xml"] = rewrite_addon_xml(files["addon.xml"], version)
    if built:
        print(f"{config.TARGET_ID}: upstream {base} -> building {version}")
        make_zip(config.TARGET_ID, version, files)
        prune(config.TARGET_ID, f"{config.TARGET_ID}-{version}.zip")
        state[config.TARGET_ID] = {"version": version, "hash": digest, "upstream": base}
    else:
        print(f"{config.TARGET_ID}: unchanged, staying at {version}")
    addon_xmls.append(files["addon.xml"].decode("utf-8"))

    # --- the repository addon ----------------------------------------------
    repo_src = os.path.join(ROOT, "repo", config.REPO_ADDON_ID)
    repo_files = collect(repo_src)
    repo_version = re.search(
        r'<addon\b[^>]*\bversion="([^"]+)"',
        repo_files["addon.xml"].decode("utf-8"),
    ).group(1)
    repo_zip = os.path.join(
        DOCS, config.REPO_ADDON_ID, f"{config.REPO_ADDON_ID}-{repo_version}.zip"
    )
    repo_digest = content_hash(repo_files)
    if repo_digest != state.get(config.REPO_ADDON_ID, {}).get("hash") or not os.path.exists(repo_zip):
        print(f"{config.REPO_ADDON_ID}: building {repo_version}")
        make_zip(config.REPO_ADDON_ID, repo_version, repo_files)
        prune(config.REPO_ADDON_ID, f"{config.REPO_ADDON_ID}-{repo_version}.zip")
        state[config.REPO_ADDON_ID] = {"version": repo_version, "hash": repo_digest}
        built = True
    addon_xmls.append(repo_files["addon.xml"].decode("utf-8"))

    # --- index Kodi reads ---------------------------------------------------
    body = "\n".join(strip_decl(x) for x in addon_xmls)
    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n{}\n</addons>\n'.format(body)
    data = addons_xml.encode("utf-8")
    write(os.path.join(DOCS, "addons.xml"), data)
    write(
        os.path.join(DOCS, "addons.xml.md5"),
        hashlib.md5(data).hexdigest().encode("ascii"),
    )
    write(os.path.join(DOCS, ".nojekyll"), b"")
    write(
        STATE_FILE,
        (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    print("BUILT=" + ("yes" if built else "no"))


if __name__ == "__main__":
    main()
