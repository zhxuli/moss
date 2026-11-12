import hashlib
import os
import re
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
USER_RUNNERS = USER_DIR / "runners.json"
USER_CONFIG = USER_DIR / "config.toml"
HISTORY_DIR = USER_DIR / "history"
STATE_DIR = USER_DIR / "state"
RESOLVE_DIR = USER_DIR / "resolve"
USER_RUNTIMES = USER_DIR / "runtimes"

def ensure_user_dirs():
    for d in (USER_DIR, USER_PKGS, STATE_DIR, HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)

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
