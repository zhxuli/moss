import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

INVOCATION_NAME = Path(sys.argv[0]).stem if len(sys.argv) > 0 else "moss"

_env_home = os.environ.get("MOSS_HOME")
HOME = Path(_env_home).resolve() if _env_home else Path(sys.argv[0]).resolve().parent

SYSTEM_DIR = HOME / "system"
SYSTEM_PKGS = SYSTEM_DIR / "pkgs"
SYSTEM_RUNNERS = SYSTEM_DIR / "runners.json"
SPEC_DIR = SYSTEM_DIR / "spec"
SPEC_FILE = SPEC_DIR / "插件契约.md"
SPEC_SCHEMA = SPEC_DIR / "pkg.schema.json"

SYSTEM_RUNTIMES = SYSTEM_DIR / "runtimes"

USER_DIR = HOME / "user_data"
USER_PKGS = USER_DIR / "pkgs"
USER_CONFIG_DIR = USER_DIR / "config"
USER_CONFIG_BACKUP_DIR = USER_CONFIG_DIR / "backups"
USER_RUNNERS = USER_CONFIG_DIR / "runners.json"
USER_CONFIG = USER_CONFIG_DIR / "config.toml"
SNAPSHOT_IGNORE = USER_CONFIG_DIR / "snapshot.ignore"
HISTORY_DIR = USER_DIR / "history"
STATE_DIR = USER_DIR / "state"
RESOLVE_DIR = USER_DIR / "resolve"
USER_RUNTIMES = USER_DIR / "runtimes"

def _unique_path(path):
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        cand = path.with_name("%s.%d%s" % (stem, i, suffix))
        if not cand.exists():
            return cand
    return path.with_name(path.name + ".legacy")

def _move_legacy_file(src, dst):
    """把旧位置的文件搬到新位置；目标已存在时绝不覆盖，旧文件进 config/backups。"""
    src, dst = Path(src), Path(dst)
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not dst.exists():
            shutil.move(str(src), str(dst))
        else:
            USER_CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            target = _unique_path(USER_CONFIG_BACKUP_DIR / src.name)
            shutil.move(str(src), str(target))
    except OSError:
        pass

def _migrate_legacy_config():
    _move_legacy_file(USER_DIR / "config.toml", USER_CONFIG)
    _move_legacy_file(USER_DIR / "runners.json", USER_RUNNERS)
    _move_legacy_file(USER_DIR / "snapshot.ignore", SNAPSHOT_IGNORE)
    for pat in ("config.toml.backup", "config.toml.bak-*",
                "runners.json.bak-*", "snapshot.ignore.bak*"):
        for src in USER_DIR.glob(pat):
            if not src.is_file():
                continue
            USER_CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            target = _unique_path(USER_CONFIG_BACKUP_DIR / src.name)
            try:
                shutil.move(str(src), str(target))
            except OSError:
                pass

def ensure_user_dirs():
    for d in (USER_DIR, USER_PKGS, USER_CONFIG_DIR, USER_CONFIG_BACKUP_DIR,
              STATE_DIR, HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_config()

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

def valid_id(pid):
    return bool(ID_RE.match(str(pid or "")))

def _short_hash(key):
    return hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]

def _readable_tag(key):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(key))
    s = s.strip(" .-")
    if len(s) > 60:
        s = s[-60:]
    return s or "dir"

def _readable_dir(key):
    return "%s__%s" % (_readable_tag(key), _short_hash(key))

def pkg_state_dir(pid):
    pid = str(pid or "")
    if not valid_id(pid):
        return STATE_DIR / "_bad" / _short_hash(pid)
    return STATE_DIR / pid

def path_state_dir(key):
    return STATE_DIR / "_path" / _readable_dir(key)

def resolve_dir_for(key):
    return RESOLVE_DIR / _readable_dir(key)

def describe():
    return {
        "invocation": INVOCATION_NAME,
        "home": str(HOME),
        "system": str(SYSTEM_DIR),
        "user": str(USER_DIR),
    }
