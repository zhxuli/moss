
import os
import json

class SettingsManager:
    # <<< NEW: Define default exclusions for the reset functionality
    DEFAULT_EXCLUSIONS = [
                '.*',              # 忽略所有以点开头的文件和文件夹 (如 .git, .vscode, .idea)
                'venv',            # 忽略 Python 虚拟环境文件夹
                'env',             # 忽略另一种 Python 虚拟环境文件夹
                '__pycache__',     # 忽略 Python 缓存文件夹
                '*.pyc',           # 忽略 Python 编译文件
                '*.pyo',           # 忽略 Python 优化编译文件
                '*.pyd',           # 忽略 Python 动态链接库
                'node_modules',    # 忽略 Node.js 依赖文件夹
                'package-lock.json', # 忽略 Node.js 包锁定文件
                'yarn.lock',       # 忽略 Yarn 锁定文件
                'images',          # 忽略常见的图片资源文件夹
                'datas',           # 忽略常见的数据文件夹
                'assets',          # 忽略资源文件夹
                'resources',       # 忽略资源文件夹
                'static',          # 忽略静态文件夹
                'media',           # 忽略媒体文件夹
                '*.log',           # 忽略所有日志文件
                '*.tmp',           # 忽略所有临时文件
                '*.temp',          # 忽略临时文件
                '*.bak',           # 忽略备份文件
                '*.swp',           # 忽略 Vim 交换文件
                '*.swo',           # 忽略 Vim 交换文件
                '*.DS_Store',      # 忽略 macOS 系统文件
                'Thumbs.db',       # 忽略 Windows 缩略图文件
                'desktop.ini',     # 忽略 Windows 桌面配置文件
                'build',           # 忽略构建输出目录
                'dist',            # 忽略分发目录
                'target',          # 忽略 Java/Rust 构建目录
                'bin',             # 忽略二进制文件目录
                'obj',             # 忽略对象文件目录
                'out',             # 忽略输出目录
                'output',          # 忽略输出目录
                'release',         # 忽略发布目录
                'debug',           # 忽略调试目录
                'icons',           # 忽略图标文件夹
                'logs',            # 忽略日志文件夹
                'temp',            # 忽略临时文件夹
                'tmp',             # 忽略临时文件夹
                'cache',           # 忽略缓存文件夹
                'backup',          # 忽略备份文件夹
                'backups',         # 忽略备份文件夹
                'test',            # 忽略测试文件夹
                'tests',           # 忽略测试文件夹
                'testing',         # 忽略测试文件夹
                'coverage',        # 忽略覆盖率报告
                'htmlcov',         # 忽略 Python 覆盖率 HTML 报告
                '*.exe',           # 忽略可执行文件
                '*.dll',           # 忽略动态链接库
                '*.so',            # 忽略 Linux 共享库
                '*.dylib',         # 忽略 macOS 动态库
                '*.zip',           # 忽略压缩包
                '*.rar',           # 忽略压缩包
                '*.7z',            # 忽略压缩包
                '*.tar.gz',        # 忽略压缩包
                '*.tgz',           # 忽略压缩包
                'vendor',          # 忽略第三方依赖目录
                'lib',             # 忽略库文件目录
                'libs',            # 忽略库文件目录
                'packages',        # 忽略包文件夹
                'deps',            # 忽略依赖文件夹
                'dependencies',    # 忽略依赖文件夹
                '*.sqlite',        # 忽略 SQLite 数据库文件
                '*.db',            # 忽略数据库文件
                '*.sqlite3',       # 忽略 SQLite3 数据库文件
                '*.pid',           # 忽略进程 ID 文件
                '*.sock',          # 忽略套接字文件
                '*.orig',          # 忽略 Git 合并冲突原始文件
                '*.rej',           # 忽略补丁拒绝文件
                '*.lock',          # 忽略锁定文件
                '*.lock.json',     # 忽略锁定文件
                '*.lock.yaml',     # 忽略锁定文件
                '*.lock.yml',      # 忽略锁定文件
                '*.lock.xml',      # 忽略锁定文件
                '*.lock.html',     # 忽略锁定文件
    ]

    def __init__(self, settings_file=None):
        if settings_file is None:
            home = os.path.expanduser("~")
            settings_dir = os.path.join(home, ".sync_repo")
            os.makedirs(settings_dir, exist_ok=True)
            self.settings_file = os.path.join(settings_dir, 'settings.json')
        else:
            self.settings_file = settings_file
        self.settings = self._load_settings()

    def _load_settings(self):
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If file doesn't exist or is corrupt, start with defaults
            return {"exclusions": self.DEFAULT_EXCLUSIONS.copy()}

    def _save_settings(self):
        with open(self.settings_file, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4)

    def get_exclusions(self):
        return self.settings.get("exclusions", [])

    def set_exclusions(self, patterns):
        """Sets the entire list of exclusion patterns."""
        self.settings["exclusions"] = patterns
        self._save_settings()

    # <<< DEPRECATED (but kept for compatibility, can be removed later)
    def add_exclusion(self, pattern):
        if pattern not in self.settings.get("exclusions", []):
            self.settings.setdefault("exclusions", []).append(pattern)
            self._save_settings()

    def remove_exclusion(self, pattern):
        if pattern in self.settings.get("exclusions", []):
            self.settings["exclusions"].remove(pattern)
            self._save_settings()
    # <<< END DEPRECATED

    # <<< NEW: Method to reset exclusions to default
    def reset_exclusions_to_default(self):
        """Resets the exclusions to the predefined default list."""
        self.settings["exclusions"] = self.DEFAULT_EXCLUSIONS.copy()
        self._save_settings()
        return self.settings["exclusions"]