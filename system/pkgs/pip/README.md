# Pip 管理器

管 **moss 自带那套 Python 运行时**里的第三方库 —— 查、装、升、卸、导出。
就是 `moss :pip` 跑的那个解释器用的那些库。

## 它管的是哪一套

不是 `moss\venv`，是自带运行时：

```
D:\python\two\moss\system\runtimes\python\3.12\python.exe
第三方库装在   ...\3.12\Lib\site-packages
```

哪一套由 `system\runtimes\default.json` 里钉住的版本决定（现在是 `"python": "3.12"`）。
机器上装了多个版本时，**本工具只动配置里那一个**。

## 命令行 = python -m pip 的前门

**除了下面几条，参数一个不改地交给 pip。** 所以 pip 的官方文档在这儿逐字通用，
`moss :pip --help` 就是 pip 自己的帮助，pip 以后加新命令这儿自动就有：

```
moss :pip install requests             moss :pip uninstall -y rich
moss :pip install "numpy==2.3.3"       moss :pip list --outdated
moss :pip install -U requests          ← 升级（= install --upgrade）
moss :pip show requests                moss :pip download requests -d .
moss :pip freeze                       moss :pip cache dir
moss :pip check                        moss :pip config list
moss :pip index versions requests      moss :pip --version
moss :pip install ./x.whl              moss :pip install -r req.txt
```

**多出来的这几条**（pip 自己没合适的，或者语义正好缺）：

```
moss :pip                     看这套环境（解释器 / 版本 / 装了多少包 / 用的哪个源）
moss :pip env                 同上
moss :pip source [名字]       看 / 切装包用的源（auto / tuna / aliyun / ustc / pypi）
moss :pip search <名字…>      查名字对不对（pip 的 search 已被官方关掉，这个只做精确查）
moss :pip web [词]            按关键词找包 → 打开 PyPI 官方搜索页
moss :pip export [文件]       导出 requirements.txt（pip 的 freeze 得靠 shell 重定向）
moss :pip gui                 开界面
```

**唯一被拦的是 `uninstall pip`** —— 卸了这套环境就装不了东西了。

## 界面

```
moss :pip gui        ← 开独立窗口
```

在 moss 里点「运行」也是这个界面（内嵌在「界面」选项卡里）。

- **已装** —— 每行左边一个首字母牌，包名 + 版本（右对齐成一列），按首字母分组。
  顶部有过滤框。**指到某一行的版本号**，右侧才出现「升级 / 卸载」
  （`pip` 自己标了「保护」，不给卸）。操作不常驻，列表才干净。
- **装新包** —— 打名字查（多个空格分开），查到点「安装」（这页按钮常亮）；
  不知道叫什么点「去网页搜」
- **可升级** —— 连 PyPI 查一遍，能单个升也能全部升
- **导出** —— 写一份 `requirements.txt`，写完能**复制**、能**删除文件**

右上角下拉是**装包用的源**；装 / 卸 / 升时右下角出「任务」抽屉，pip 输出实时滚动。

## 关于「搜包」

**按关键词搜在 PyPI 官方已经关掉了**——`pip search` 那个 XML-RPC 接口现在直接回
"PyPI no longer supports 'pip search'"，`pypi.org/search` 网页又是 JS 渲染的挑战页。
所以分两条路：

- **知道名字**：`moss :pip search requests` —— 走 pip 自己那条 `/pypi/<名>/json`，
  1 秒多就回。拼错直接告诉你「PyPI 上没有这个名字」。
- **不知道叫什么**：`moss :pip web pdf` 开官方搜索页（唯一还开着的入口）。

## 装包用的源（镜像）

默认 `auto` = **不覆盖 pip 自己的配置**（`pip.ini` 里写什么就用什么）。
切国内镜像走的是 pip 标准的 `PIP_INDEX_URL`，不动你的 pip.ini，切完立刻生效：

```
moss :pip source            # 看当前 + pip.ini 内容
moss :pip source tuna       # 清华  （实测装 six 2.59s，官方 4.06s）
moss :pip source aliyun     # 阿里云（3.05s）
moss :pip source ustc       # 中科大
moss :pip source pypi       # 强制官方
moss :pip source auto       # 改回跟 pip.ini 走（默认）
```

**注意**：镜像的元数据会落后于官方。实测清华的 `requests` 详情给 2.32.3，官方已 2.34.2
—— 所以「可升级」列表会跟着源变。要最新版就切回 `auto`/`pypi` 再查。

## 数据放在哪

```
<MOSS_PLUGIN_DATA_DIR>\source.json       你选的源（auto 时没有这个文件）
<MOSS_PLUGIN_DATA_DIR>\requirements.txt  默认导出位置
```

## 注意

- 装东西**直接装进宿主运行时**，装坏了所有 `runner: python` 的包都会受影响。
  想给某个插件单独装库，用 `pkglib`（装进那个包自己的 `packages\`）。
