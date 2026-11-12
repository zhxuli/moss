from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

SPEC = 1
HASH_NAME = "blake2b-160"
DIGEST_SIZE = 20
CHUNK = 1024 * 1024

DEFAULT_EXCLUDES = [".*", "__pycache__", "*.pyc", "*.pyo", ".git", ".venv", "venv",
                    "node_modules", ".DS_Store", "Thumbs.db", "*.tmp"]

PATH_EXCLUDES = ["user/trash", "user/state"]

IGNORE_NAME = "snapshot.ignore"
IGNORE_TEMPLATE = ""

PRESET_FILTERS = [
    {"id": "logs",     "label": "日志",          "pat": ["*.log"],
     "why": "跑起来才产生的日志，通常不用留版本"},
    {"id": "media",    "label": "视频 / 音频",    "pat": ["*.mp4", "*.mov", "*.avi", "*.mkv", "*.mp3", "*.wav"],
     "why": "又大又不常改 —— 快照会很占地方"},
    {"id": "design",   "label": "设计稿 / 大图",  "pat": ["*.psd", "*.ai", "*.sketch", "*.xcf"],
     "why": "源文件很大，通常另有备份"},
    {"id": "cache",    "label": "缓存 / 编译产物", "pat": ["__pycache__", "*.pyc", "*.pyo", "*.class", "*.o"],
     "why": "每次跑都会变，留了全是噪音（内置已经有了）"},
    {"id": "venv",     "label": "虚拟环境",       "pat": ["venv", ".venv", "env", "site-packages"],
     "why": "几千个文件、随时能重建（内置已有 venv / .venv）"},
    {"id": "deps",     "label": "依赖 / 构建",    "pat": ["node_modules", "dist", "build", "target", ".next"],
     "why": "能一键重装/重编，占地方"},
    {"id": "temp",     "label": "临时 / 备份文件", "pat": ["*.tmp", "*.bak", "*.old", "*~", "*.swp"],
     "why": "临时产物（内置已有 *.tmp）"},
    {"id": "archive",  "label": "压缩包",         "pat": ["*.zip", "*.7z", "*.rar", "*.tar.gz"],
     "why": "大且通常别处也有"},
    {"id": "db",       "label": "数据库文件",      "pat": ["*.db", "*.sqlite", "*.sqlite3", "*.mdb"],
     "why": "二进制、每次都变；要留就留导出脚本"},
    {"id": "dot",      "label": "点开头的隐藏项",  "pat": [".*"],
     "why": "含 .git / .env / .idea —— 勾了会连 .env 一起排掉（内置已经有 .*）"},
]

def glob_hit(name, pats):
    for p in pats:
        if match_rules(name, [p], is_dir=True) or match_rules(name, [p]):
            return True
    return False

def parse_ignore(text):
    out = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out

def glob_to_re(pat):
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            k = pat.find("]", i + 1)
            if k < 0:
                out.append(re.escape(c))
            else:
                out.append(pat[i:k + 1])
                i = k + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)

def match_rules(name, rules, is_dir=False):
    hit = False
    for r in rules:
        neg = r.startswith("!")
        pat = r[1:] if neg else r
        if not pat:
            continue
        if pat.endswith("/"):
            if not is_dir:
                continue
            pat = pat.rstrip("/")
        if "/" in pat or not pat:
            continue
        try:
            if re.fullmatch(glob_to_re(pat.lower()), str(name).lower()):
                hit = not neg
        except re.error:
            pass
    return hit

def match_path(rel, rules):
    rel = str(rel or "").replace("\\", "/").strip("/").lower()
    hit = False
    for r in rules:
        neg = r.startswith("!")
        pat = r[1:] if neg else r
        pat = pat.replace("\\", "/").strip()
        if not pat or "/" not in pat.strip("/"):
            continue
        dir_only = pat.endswith("/")
        anchored = pat.startswith("/")
        pat = pat.strip("/")
        if not pat:
            continue
        cands = [glob_to_re(pat)]
        if not anchored:
            cands.append(glob_to_re("**/" + pat))
        ok = False
        for rx in cands:
            try:
                if re.fullmatch(rx, rel):
                    ok = True
                    break
                if re.fullmatch(rx + "(?:/.*)?", rel):
                    ok = True
                    break
            except re.error:
                continue
        if ok and (not dir_only or "/" in rel or True):
            hit = not neg
    return hit
STORE_DIRNAME = "backups"
OBJECTS_DIRNAME = "objects"

GROUP_RE = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9_.@-]{0,63}$")

def safe_group(name, fallback="@misc"):
    n = re.sub(r"[^A-Za-z0-9_.@-]+", "-", str(name or "").strip()).strip("-.")
    n = n[:64]
    if not n or not GROUP_RE.match(n):
        n = fallback
    return n

def group_for_sources(sources):
    srcs = [str(x or "") for x in (sources or [])]
    for s0 in srcs:
        parts = s0.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[1] in ("pkgs", "state"):
            return safe_group(parts[2])
    for s0 in srcs:
        if s0 in ("user", "system"):
            return "@" + s0
    if srcs:
        first = srcs[0].rstrip("/")
        tail = first.split("/")[-1] or "misc"
        pre = "@abs-" if first.startswith("abs/") else "@dir-"
        import hashlib
        h = hashlib.blake2b(first.lower().encode("utf-8"), digest_size=4).hexdigest()
        head = safe_group(pre.rstrip("-"))
        nice = safe_group(tail)
        return (head + ("-" + nice if nice else "") + "-" + h)[:64]
    return "@misc"

def _now_text(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t or time.time()))

def new_id(now=None):
    t = now or time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + "-" + os.urandom(2).hex()

def hash_file(path, chunk=CHUNK):
    h = hashlib.blake2b(digest_size=DIGEST_SIZE)
    size = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            size += len(b)
    return h.hexdigest(), size

def hash_bytes(data):
    h = hashlib.blake2b(digest_size=DIGEST_SIZE)
    h.update(data)
    return h.hexdigest()

class BackupStore:
    def __init__(self, root, rel_of, resolve, excludes=None, trash=None, log=None):
        self.root = Path(root)
        self.rel_of = rel_of
        self.resolve = resolve
        self.excludes = list(DEFAULT_EXCLUDES if excludes is None else excludes)
        self.ignore_file = Path(root).parent / IGNORE_NAME
        if excludes is None:
            self.excludes += parse_ignore(self._read_ignore())
        self.trash = trash
        self.log = log
        self._migrating = False

    def _say(self, text):
        try:
            if self.log:
                self.log(text)
        except Exception:
            pass

    def group_dir(self, group):
        g = safe_group(group)
        if not GROUP_RE.match(g):
            raise ValueError("分组名不合法：%r" % (group,))
        return self.root / g

    def objects(self, group):
        return self.group_dir(group) / OBJECTS_DIRNAME

    def tmp(self, group):
        return self.objects(group) / "_tmp"

    def ensure(self, group):
        self.tmp(group).mkdir(parents=True, exist_ok=True)

    def object_path(self, group, fp):
        return self.objects(group) / str(fp)[:2] / str(fp)

    def groups(self):
        if not self.root.is_dir():
            return []
        out = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if d.name == OBJECTS_DIRNAME:
                continue
            if self._ids_in(d):
                out.append(d.name)
        return out

    def _ids_in(self, gdir):
        if not gdir.is_dir():
            return []
        return sorted((d.name for d in gdir.iterdir()
                       if d.is_dir() and (d / "manifest.json").is_file()), reverse=True)

    def ids(self, group=None):
        if group is not None:
            return self._ids_in(self.group_dir(group))
        out = []
        for g in self.groups():
            out.extend(self._ids_in(self.root / g))
        return out

    def _find(self, bid):
        bid = str(bid or "")
        if not bid or "/" in bid or "\\" in bid or bid.startswith("."):
            raise ValueError("备份 id 不合法：%r" % (bid,))
        for g in self.groups():
            d = self.root / g / bid
            if (d / "manifest.json").is_file():
                return g, d
        return None, None

    def _backup_dir(self, group, bid):
        return self.group_dir(group) / str(bid)

    def ensure_layout(self):
        if getattr(self, "_migrating", False):
            return {"migrated": 0, "skipped": True}
        self._migrating = True
        try:
            return self._migrate_legacy()
        finally:
            self._migrating = False

    def _migrate_legacy(self):
        if not self.root.is_dir():
            return {"migrated": 0}
        legacy_obj = self.root / OBJECTS_DIRNAME
        legacy_ids = self._ids_in(self.root)
        if not legacy_ids and not legacy_obj.is_dir():
            return {"migrated": 0}
        moved = 0
        for bid in legacy_ids:
            d = self.root / bid
            try:
                man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            except Exception as e:
                dest = self.root / "@broken"
                dest.mkdir(parents=True, exist_ok=True)
                target = dest / bid
                if not target.exists():
                    shutil.move(str(d), str(target))
                self._say("备份库迁移：清单坏的 %s 挪到 @broken（%s）" % (bid, e))
                continue
            group = safe_group(man.get("group") or group_for_sources(man.get("sources")))
            dest = self.root / group
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / bid
            if target.exists():
                shutil.rmtree(d, ignore_errors=True)
                continue
            shutil.move(str(d), str(target))
            moved += 1
            self._say("备份库迁移：%s → %s/%s（按来源归组）" % (bid, group, bid))
            for e in man.get("files") or []:
                fp = e.get("fp")
                if not fp:
                    continue
                src = legacy_obj / fp[:2] / fp
                if not src.is_file():
                    continue
                dst = self.object_path(group, fp)
                try:
                    if dst.is_file():
                        src.unlink(missing_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(dst))
                except OSError as ex:
                    self._say("备份库迁移：搬内容块 %s 失败（%s）" % (fp[:10], ex))
                else:
                    try:
                        src.parent.rmdir()
                    except OSError:
                        pass
        if legacy_obj.is_dir():
            left = [f for b in legacy_obj.iterdir() if b.is_dir() for f in b.iterdir()
                    if f.is_file()]
            if not left:
                shutil.rmtree(legacy_obj, ignore_errors=True)
            else:
                self._say("备份库迁移：老对象目录还剩 %d 个没人认领的内容块，先留着" % len(left))
        if moved:
            self._say("备份库迁移：共挪了 %d 次备份（按包 id 分组）" % moved)
        return {"migrated": moved}

    def presets(self, sources, cap=20000):
        counts = {p["id"]: 0 for p in PRESET_FILTERS}
        samples = {p["id"]: [] for p in PRESET_FILTERS}
        seen = 0
        for src in (sources or []):
            base = Path(str(src))
            if not base.exists():
                try:
                    base = self.resolve(src)
                except Exception:
                    continue
            if not base.is_dir():
                base = base.parent if base.is_file() else None
            if base is None:
                continue
            for cur, dirs, names in os.walk(base):
                cp = Path(cur)
                keep = []
                for d in sorted(dirs):
                    for pr in PRESET_FILTERS:
                        if glob_hit(d, pr["pat"]):
                            counts[pr["id"]] += 1
                            if len(samples[pr["id"]]) < 3:
                                samples[pr["id"]].append(self.rel_of(cp / d) or d)
                    if self._skip_dir_name(d, is_dir=True) or self._skip_rel(self.rel_of(cp / d) or ""):
                        continue
                    keep.append(d)
                dirs[:] = keep
                for n in sorted(names):
                    seen += 1
                    if seen > cap:
                        break
                    for pr in PRESET_FILTERS:
                        if glob_hit(n, pr["pat"]):
                            counts[pr["id"]] += 1
                            if len(samples[pr["id"]]) < 3:
                                samples[pr["id"]].append(self.rel_of(cp / n) or n)
                if seen > cap:
                    break
        out = []
        for pr in PRESET_FILTERS:
            it = dict(pr)
            it["hit"] = counts[pr["id"]]
            it["sample"] = samples[pr["id"]]
            out.append(it)
        out.sort(key=lambda x: (-x["hit"], x["id"]))
        return out

    def group_ignore_file(self, group):
        return self.group_dir(group) / "ignore"

    def group_ignore(self, group):
        try:
            f = self.group_ignore_file(group)
            return parse_ignore(f.read_text(encoding="utf-8", errors="replace")) if f.is_file() else []
        except Exception:
            return []

    def _read_ignore(self):
        try:
            if not self.ignore_file.is_file():
                self.ignore_file.parent.mkdir(parents=True, exist_ok=True)
                self.ignore_file.write_text(IGNORE_TEMPLATE, encoding="utf-8")
                _lg = getattr(self, "log", None)
                if _lg: _lg("快照过滤：生成了模板 %s" % self.ignore_file)
                return IGNORE_TEMPLATE
            return self.ignore_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            _lg = getattr(self, "log", None)
            if _lg: _lg("快照过滤：%s 读不出来（%s），这次只用内置那几条" % (self.ignore_file, e))
            return ""

    def _rules(self):
        return list(self.excludes)

    def _skip_dir_name(self, name, is_dir=False):
        return match_rules(name, self._rules(), is_dir=is_dir)

    def _skip_rel(self, rel):
        if match_path(rel, self._rules()):
            return True
        for pre in PATH_EXCLUDES:
            if rel == pre or rel.startswith(pre + "/"):
                return True
        return False

    def create(self, sources, title="", note="", excludes=None, group=None,
               by="", by_task=""):
        self.ensure_layout()
        srcs_rel = []
        for s in sources:
            try:
                r = self.rel_of(Path(s))
            except Exception:
                r = None
            if r:
                srcs_rel.append(r)
        g = safe_group(group) if group else group_for_sources(srcs_rel)
        self.ensure(g)
        ex = list(self.excludes) + self.group_ignore(g) + list(excludes or [])
        saved_ex = self.excludes
        self.excludes = ex
        try:
            return self._create(sources, title, note, g, by=by, by_task=by_task)
        finally:
            self.excludes = saved_ex

    def _create(self, sources, title, note, group, by="", by_task=""):
        bid = new_id()
        files = []
        empty_dirs = []
        skipped = []
        errors = []
        new_objects = 0
        new_bytes = 0
        seen = set()
        store_prefix = str(self.root.resolve())

        def walk_dir(base: Path, rel_base: str):
            for cur, dirs, names in os.walk(base):
                curp = Path(cur)
                keep = []
                for d in sorted(dirs):
                    if self._skip_dir_name(d, is_dir=True):
                        continue
                    sub_rel = (rel_base + "/" + d) if rel_base else d
                    if self._skip_rel(sub_rel):
                        continue
                    if str((curp / d).resolve()).startswith(store_prefix):
                        continue
                    keep.append(d)
                dirs[:] = keep
                if not names and not dirs:
                    r = self.rel_of(curp)
                    if r and r not in empty_dirs:
                        empty_dirs.append(r)
                for n in sorted(names):
                    if self._skip_dir_name(n):
                        continue
                    if self._skip_rel((rel_base + "/" + n) if rel_base else n):
                        continue
                    self._take(curp / n, group, files, seen, skipped, errors)

        for src in sources:
            p = Path(src)
            if p.is_dir():
                r = self.rel_of(p)
                walk_dir(p, r or "")
            elif p.is_file():
                self._take(p, group, files, seen, skipped, errors)
            else:
                skipped.append(str(p))

        for e in files:
            if e.pop("_new", False):
                new_objects += 1
                new_bytes += e["size"]

        total_bytes = sum(e["size"] for e in files)
        man = {
            "spec": SPEC,
            "id": bid,
            "group": group,
            "title": (title or "").strip() or ("备份 " + _now_text()),
            "note": (note or "").strip(),
            "by": str(by or "").strip(),
            "by_task": str(by_task or "").strip(),
            "created": time.time(),
            "created_text": _now_text(),
            "hash": HASH_NAME,
            "sources": [self.rel_of(Path(s)) or str(s) for s in sources],
            "exclude": list(self.excludes),
            "files": files,
            "empty_dirs": empty_dirs,
            "skipped": skipped[:200],
            "errors": errors[:200],
            "stats": {"files": len(files), "bytes": total_bytes,
                      "new_objects": new_objects, "new_bytes": new_bytes,
                      "empty_dirs": len(empty_dirs),
                      "skipped": len(skipped), "errors": len(errors)},
        }
        d = self._backup_dir(group, bid)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "manifest.json.tmp"
        tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, d / "manifest.json")
        return man

    def _take(self, path: Path, group, files, seen, skipped, errors):
        try:
            if path.is_symlink():
                skipped.append(str(path))
                return
            rel = self.rel_of(path)
            if not rel or rel in seen:
                skipped.append(str(path))
                return
            if self._skip_rel(rel):
                skipped.append(str(path))
                return
            fp, size = hash_file(path)
            seen.add(rel)
            files.append({"rel": rel, "fp": fp, "size": size,
                          "mtime": int(path.stat().st_mtime)})
            if not self.object_path(group, fp).is_file():
                self._put_object(group, path, fp)
                files[-1]["_new"] = True
        except OSError as e:
            errors.append("%s：%s" % (path, e))

    def _put_object(self, group, src: Path, fp):
        for attempt in (1, 2):
            self.ensure(group)
            tmp = self.tmp(group) / ("%s.%d.%s" % (fp[:12], os.getpid(), os.urandom(3).hex()))
            shutil.copyfile(src, tmp)
            again = hash_file(tmp)[0]
            if again != fp:
                tmp.unlink(missing_ok=True)
                if attempt == 2:
                    raise OSError("这个文件在备份过程中一直在变（跳过）：%s" % src)
                fp, _ = hash_file(src)
                continue
            dest = self.object_path(group, fp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_file():
                tmp.unlink(missing_ok=True)
                return
            os.replace(tmp, dest)
            return

    def manifest(self, bid, group=None):
        if group is not None:
            p = self._backup_dir(group, bid) / "manifest.json"
            if not p.is_file():
                raise ValueError("这个分组里没有这次备份：%s/%s" % (group, bid))
            return json.loads(p.read_text(encoding="utf-8"))
        g, d = self._find(bid)
        if not d:
            raise ValueError("没有这次备份：%s" % bid)
        return json.loads((d / "manifest.json").read_text(encoding="utf-8"))

    def _group_of(self, bid, group=None):
        if group:
            return safe_group(group)
        g, d = self._find(bid)
        if not d:
            raise ValueError("没有这次备份：%s" % bid)
        return g

    def list_backups(self, group=None):
        self.ensure_layout()
        out = []
        gs = [self.group_dir(group).name] if group else self.groups()
        for g in gs:
            for bid in self._ids_in(self.root / g):
                try:
                    m = self.manifest(bid, g)
                except Exception as e:
                    out.append({"id": bid, "group": g, "broken": str(e),
                                "title": "(清单读不出来)", "files": 0, "bytes": 0,
                                "created_text": ""})
                    continue
                st = m.get("stats") or {}
                out.append({"id": bid, "group": m.get("group") or g,
                            "title": m.get("title") or bid, "note": m.get("note") or "",
                            "by": m.get("by") or "", "by_task": m.get("by_task") or "",
                            "created": m.get("created"),
                            "created_text": m.get("created_text") or "",
                            "sources": m.get("sources") or [],
                            "files": st.get("files", len(m.get("files") or [])),
                            "bytes": st.get("bytes", 0),
                            "new_objects": st.get("new_objects", 0),
                            "new_bytes": st.get("new_bytes", 0),
                            "skipped": st.get("skipped", 0), "errors": st.get("errors", 0)})
        out.sort(key=lambda x: str(x.get("created") or ""), reverse=True)
        return out

    def _locate_object(self, fp, group=None):
        if group:
            p = self.object_path(group, fp)
            return p if p.is_file() else None
        for g in self.groups():
            p = self.object_path(g, fp)
            if p.is_file():
                return p
        return None

    def read_blob(self, fp, limit=200000, group=None):
        fp = str(fp or "")
        if not fp or "/" in fp or "\\" in fp or ".." in fp:
            raise ValueError("指纹不合法")
        p = self._locate_object(fp, group)
        if not p:
            return {"ok": False, "msg": "对象缺失（可能被手工删了）：%s" % fp}
        size = p.stat().st_size
        raw = p.read_bytes()[:limit]
        try:
            text = raw.decode("utf-8")
            return {"ok": True, "binary": False, "size": size, "truncated": size > limit,
                    "text": text, "fp": fp}
        except UnicodeDecodeError:
            return {"ok": True, "binary": True, "size": size, "truncated": size > limit,
                    "fp": fp, "head": raw[:64].hex(" ")}

    def plan(self, bid, rels=None, only="all", sync=False, group=None):
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        rows = []
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            try:
                target = self.resolve(rel)
            except Exception as ex:
                rows.append({"rel": rel, "action": "error", "why": str(ex)})
                continue
            fp = e.get("fp")
            exists = target.exists()
            same = False
            if exists and target.is_file():
                try:
                    same = (hash_file(target)[0] == fp)
                except OSError:
                    same = False
            have_obj = self.object_path(g, fp).is_file()
            if not have_obj:
                action, why = "error", "对象缺失（备份库里的内容被删了）"
            elif not exists:
                action, why = "create", ""
            elif same:
                action, why = "same", "和备份里一模一样"
            else:
                action, why = "overwrite", "现在的内容和备份里不一样"
            if only == "missing" and action == "overwrite":
                action, why = "skip", "现在有（这次只补缺的）"
            if only == "changed" and action == "same":
                action, why = "skip", "已经一样"
            rows.append({"rel": rel, "action": action, "why": why, "fp": fp,
                         "size": e.get("size", 0)})
        if sync and want is None:
            rows.extend(self._extras(m))
        cnt = {}
        for r in rows:
            cnt[r["action"]] = cnt.get(r["action"], 0) + 1
        return {"ok": True, "id": bid, "group": g, "title": m.get("title") or bid,
                "rows": rows, "counts": cnt, "empty_dirs": m.get("empty_dirs") or [],
                "sources": m.get("sources") or []}

    def _extras(self, m):
        _saved_ex = self.excludes
        self.excludes = list(m.get("exclude") or self.excludes)
        known = set(e.get("rel") for e in (m.get("files") or []))
        out = []
        store_prefix = str(self.root.resolve())
        for src in (m.get("sources") or []):
            try:
                base = self.resolve(src)
            except Exception:
                continue
            if not base.is_dir():
                continue
            for cur_dir, dirs, names in os.walk(base):
                curp = Path(cur_dir)
                dirs[:] = [d for d in sorted(dirs)
                           if not self._skip_dir_name(d, is_dir=True)
                           and not str((curp / d).resolve()).startswith(store_prefix)]
                for n in sorted(names):
                    if self._skip_dir_name(n):
                        continue
                    if self._skip_rel(self.rel_of(curp / n) or ""):
                        continue
                    p = curp / n
                    if p.is_symlink():
                        continue
                    rel = self.rel_of(p)
                    if not rel or rel in known or self._skip_rel(rel):
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    out.append({"rel": rel, "action": "extra", "fp": "", "size": size,
                                "why": "现在多出来的（同步模式会挪进回收站）"})
        self.excludes = _saved_ex
        return out

    def restore(self, bid, rels=None, only="all", sync=False, group=None):
        g = self._group_of(bid, group)
        plan = self.plan(bid, rels, only, sync=sync, group=g)
        m = self.manifest(bid, g)
        by_rel = {e["rel"]: e for e in (m.get("files") or [])}
        done, skipped, errors, trashed = [], [], [], []
        for r in plan["rows"]:
            if r["action"] in ("same", "skip"):
                skipped.append(r["rel"])
                continue
            if r["action"] == "error":
                errors.append("%s：%s" % (r["rel"], r.get("why") or ""))
                continue
            if r["action"] == "extra":
                try:
                    t = self.resolve(r["rel"])
                except Exception as ex:
                    errors.append("%s：%s" % (r["rel"], ex))
                    continue
                try:
                    if self.trash:
                        self.trash(t)
                    else:
                        t.unlink()
                    trashed.append(r["rel"])
                except OSError as ex:
                    errors.append("%s：%s" % (r["rel"], ex))
                continue
            e = by_rel.get(r["rel"]) or {}
            src = self.object_path(g, e.get("fp") or "")
            try:
                target = self.resolve(r["rel"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if r["action"] == "overwrite":
                    bak = target.with_name(target.name + ".bak")
                    try:
                        shutil.copyfile(target, bak)
                    except OSError:
                        pass
                shutil.copyfile(src, target)
                if e.get("mtime"):
                    try:
                        os.utime(target, (e["mtime"], e["mtime"]))
                    except OSError:
                        pass
                done.append(r["rel"])
            except OSError as ex:
                errors.append("%s：%s" % (r["rel"], ex))
        made_dirs = []
        for rel in plan.get("empty_dirs") or []:
            try:
                d = self.resolve(rel)
                if not d.exists():
                    d.mkdir(parents=True, exist_ok=True)
                    made_dirs.append(rel)
            except Exception:
                pass
        return {"ok": True, "id": bid, "group": g, "restored": done, "skipped": skipped,
                "errors": errors, "dirs": made_dirs, "trashed": trashed,
                "counts": {"restored": len(done), "skipped": len(skipped),
                           "errors": len(errors), "dirs": len(made_dirs),
                           "trashed": len(trashed)}}

    def _rel_in_backup(self, man, rel):
        srcs = [str(x) for x in (man.get("sources") or []) if x]
        hits = [s for s in srcs if rel == s or rel.startswith(s.rstrip("/") + "/")]
        if not hits:
            base = rel.split("/")[-1] or "file"
            return (srcs and len(srcs) > 1) and (base,) or base
        s = max(hits, key=len)
        tail = rel[len(s):].lstrip("/")
        if len(srcs) > 1:
            head = s.rstrip("/").split("/")[-1]
            return head + "/" + tail if tail else head
        return tail or rel.split("/")[-1]

    def export(self, bid, target, subpath="", rels=None, keep_bak=False, group=None):
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        base = Path(target).expanduser()
        sub = str(subpath or "").strip().strip("/\\").replace("\\", "/")
        if ".." in sub.split("/"):
            raise ValueError("子路径里不许有 `..`")
        if sub:
            base = base / sub
        written, bak, errors = [], [], []
        total = 0
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            fp = e.get("fp")
            src = self.object_path(g, fp)
            if not src.is_file():
                errors.append("%s：备份库里的内容块缺失" % rel)
                continue
            dest = base / self._rel_in_backup(m, rel)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and keep_bak:
                    try:
                        shutil.copyfile(dest, str(dest) + ".bak")
                        bak.append(str(dest) + ".bak")
                    except OSError:
                        pass
                shutil.copyfile(src, dest)
                if e.get("mtime"):
                    try:
                        os.utime(dest, (e["mtime"], e["mtime"]))
                    except OSError:
                        pass
                written.append(str(dest))
                total += e.get("size", 0)
            except OSError as ex:
                errors.append("%s：%s" % (rel, ex))
        for rel in m.get("empty_dirs") or []:
            try:
                (base / self._rel_in_backup(m, rel)).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        return {"ok": True, "id": bid, "group": g, "root": str(base), "written": written,
                "bytes": total, "bak": bak, "errors": errors,
                "counts": {"written": len(written), "errors": len(errors), "bak": len(bak)}}

    def export_plan(self, bid, target, subpath="", rels=None, group=None):
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        sub = str(subpath or "").strip().strip("/\\").replace("\\", "/")
        base = Path(target).expanduser()
        if sub:
            base = base / sub
        new_n = over_n = 0
        samples = []
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            dest = base / self._rel_in_backup(m, rel)
            if dest.exists():
                over_n += 1
                if len(samples) < 3:
                    samples.append(str(dest))
            else:
                new_n += 1
        return {"ok": True, "root": str(base), "new": new_n, "overwrite": over_n,
                "files": new_n + over_n, "samples": samples,
                "bytes": sum(e.get("size", 0) for e in (m.get("files") or [])
                             if want is None or e.get("rel") in want)}

    def rename_group(self, old, new):
        self.ensure_layout()
        o, n = safe_group(old), safe_group(new)
        if o == n:
            return {"ok": True, "renamed": 0, "msg": "名字没变"}
        src, dst = self.root / o, self.root / n
        if not src.is_dir():
            return {"ok": True, "renamed": 0, "msg": "没有这个分组（不用改）"}
        dst.mkdir(parents=True, exist_ok=True)
        moved = 0
        for bid in self._ids_in(src):
            target = dst / bid
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(src / bid), str(target))
            moved += 1
        src_obj = src / OBJECTS_DIRNAME
        if src_obj.is_dir():
            for bucket in src_obj.iterdir():
                if not bucket.is_dir() or bucket.name == "_tmp":
                    continue
                for f in bucket.iterdir():
                    if not f.is_file():
                        continue
                    d = self.object_path(n, f.name)
                    if not d.is_file():
                        d.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(d))
        shutil.rmtree(src, ignore_errors=True)
        for bid in self._ids_in(dst):
            try:
                m = self.manifest(bid, n)
                if m.get("group") != n:
                    m["group"] = n
                    (dst / bid / "manifest.json").write_text(
                        json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:
                pass
        self._say("备份库：分组改名 %s → %s（%d 次备份）" % (o, n, moved))
        return {"ok": True, "renamed": moved, "msg": "分组已改名：%s → %s" % (o, n)}

    def drop_group(self, group):
        self.ensure_layout()
        g = safe_group(group)
        d = self.root / g
        if not d.is_dir():
            return {"ok": True, "removed": 0, "freed": 0, "msg": "没有这个分组"}
        backups = len(self._ids_in(d))
        size = 0
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)
        self._say("备份库：删掉整个分组 %s（%d 次备份、%s 字节）" % (g, backups, size))
        return {"ok": True, "removed": backups, "freed": size,
                "msg": "已删掉分组「%s」：%d 次备份、%s" % (g, backups, size)}

    def delete_ai(self, bid=None, group=None):
        self.ensure_layout()
        if not bid and not group:
            return {"ok": False, "deleted": [], "skipped": [],
                    "msg": "不给 id 就必须给 group（不许「顺手清全库」）"}
        targets = []
        if bid:
            g = self._group_of(bid, group)
            m = self.manifest(bid, g)
            targets = [(bid, g, m)]
        else:
            g = safe_group(group)
            for one in self._ids_in(self.root / g):
                try:
                    targets.append((one, g, self.manifest(one, g)))
                except Exception:
                    continue
        deleted, skipped = [], []
        for one, g, m in targets:
            if str(m.get("by") or "") != "ai":
                skipped.append(one)
                continue
            self.delete(one, g)
            deleted.append(one)
        if not deleted:
            return {"ok": True, "deleted": [], "skipped": skipped,
                    "msg": ("没有 AI 存的快照可清" + ("（跳过 %d 条你存的）" % len(skipped) if skipped else ""))}
        return {"ok": True, "deleted": deleted, "skipped": skipped,
                "msg": "清掉 %d 条 AI 存的快照%s"
                       % (len(deleted), ("（你存的 %d 条一条没动）" % len(skipped)) if skipped else "")}

    def delete(self, bid, group=None):
        g = self._group_of(bid, group)
        d = self._backup_dir(g, bid)
        if not (d / "manifest.json").is_file():
            raise ValueError("没有这次备份：%s" % bid)
        shutil.rmtree(d)
        gc = self.gc(group=g)
        gc["pruned"] = self._prune_group(g)
        gc["deleted"] = bid
        gc["group"] = g
        return gc

    def _prune_group(self, group):
        d = self.root / safe_group(group)
        if not d.is_dir() or self._ids_in(d):
            return False
        shutil.rmtree(d, ignore_errors=True)
        return not d.exists()

    def gc(self, dry_run=False, group=None):
        self.ensure_layout()
        gs = [safe_group(group)] if group else self.groups()
        removed, freed, kept, refs_all = [], 0, 0, 0
        for g in gs:
            refs = set()
            for bid in self._ids_in(self.root / g):
                try:
                    m = self.manifest(bid, g)
                except Exception:
                    continue
                for e in m.get("files") or []:
                    if e.get("fp"):
                        refs.add(e["fp"])
            refs_all += len(refs)
            objdir = self.objects(g)
            if objdir.is_dir():
                for bucket in sorted(objdir.iterdir()):
                    if bucket.name == "_tmp":
                        if not dry_run:
                            for f in bucket.iterdir():
                                try:
                                    f.unlink()
                                except OSError:
                                    pass
                        continue
                    if not bucket.is_dir():
                        continue
                    for f in sorted(bucket.iterdir()):
                        if not f.is_file():
                            continue
                        if f.name in refs:
                            kept += 1
                            continue
                        try:
                            sz = f.stat().st_size
                            if not dry_run:
                                f.unlink()
                            removed.append(g + "/" + f.name)
                            freed += sz
                        except OSError:
                            pass
                    if not dry_run:
                        try:
                            bucket.rmdir()
                        except OSError:
                            pass
        if not dry_run:
            for g in gs:
                self._prune_group(g)
        return {"ok": True, "dry_run": bool(dry_run), "removed": len(removed),
                "removed_fps": removed[:100], "freed": freed, "kept": kept,
                "referenced": refs_all}

    def stat(self, group=None):
        backups = self.list_backups(group)
        all_bytes = sum(b.get("bytes") or 0 for b in backups)
        all_files = sum(b.get("files") or 0 for b in backups)
        obj_bytes = obj_n = 0
        gs = [safe_group(group)] if group else self.groups()
        for g in gs:
            objdir = self.objects(g)
            if not objdir.is_dir():
                continue
            for bucket in objdir.iterdir():
                if not bucket.is_dir() or bucket.name == "_tmp":
                    continue
                for f in bucket.iterdir():
                    if f.is_file():
                        obj_n += 1
                        try:
                            obj_bytes += f.stat().st_size
                        except OSError:
                            pass
        return {"ok": True, "groups": len(self.groups()), "backups": len(backups),
                "files": all_files, "all_bytes": all_bytes, "objects": obj_n,
                "store_bytes": obj_bytes, "saved": max(0, all_bytes - obj_bytes),
                "root": str(self.root), "group": safe_group(group) if group else ""}

    def groups_summary(self):
        self.ensure_layout()
        out = []
        for g in self.groups():
            st = self.stat(g)
            items = self.list_backups(g)
            out.append({"group": g, "backups": st["backups"], "files": st["files"],
                        "bytes": st["all_bytes"], "objects": st["objects"],
                        "store_bytes": st["store_bytes"], "saved": st["saved"],
                        "last": (items[0].get("created_text") if items else ""),
                        "last_title": (items[0].get("title") if items else "")})
        out.sort(key=lambda x: str(x.get("last") or ""), reverse=True)
        return out

    def check(self, bid=None, group=None):
        gs = [safe_group(group)] if group else self.groups()
        out = []
        for g in gs:
            ids = [bid] if bid else self._ids_in(self.root / g)
            for b in ids:
                try:
                    m = self.manifest(b, g)
                except Exception as e:
                    out.append({"id": b, "group": g, "broken": str(e)})
                    continue
                miss = [e["rel"] for e in (m.get("files") or [])
                        if e.get("fp") and not self.object_path(g, e["fp"]).is_file()]
                out.append({"id": b, "group": g, "missing": len(miss),
                            "sample": miss[:10]})
        return {"ok": True, "rows": out}
