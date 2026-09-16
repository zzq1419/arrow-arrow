# 一箭又一箭 · Python / Pygame 版

> 软件工程课程第二次个人作业。用 Python + Pygame 实现的点击式箭头解谜小游戏，
> 参考微信小游戏《一箭又一箭》的**核心玩法**，关卡、代码、绘制全部自己实现，
> 没有使用原游戏的素材、代码、音效或关卡。

## 下载即玩（Windows 免安装版）

不想装 Python 的同学，直接下载打包好的免安装版，**双击就能玩**：

**➡ [点此下载 一箭又一箭 v1.0（Windows 64 位，约 15 MB）](https://github.com/zzq1419/arrow-arrow/releases/latest)**

下载后双击 `ArrowArrow-v1.0-win64.exe` 即可开始游戏，目标电脑**不需要安装 Python
或 pygame**。首次运行时 Windows SmartScreen 可能会拦一下，点「更多信息」→「仍要运行」
就能继续（PyInstaller 打包的程序常见提示）。

想看源码、用 macOS / Linux，或者想自己改代码的，按第四节「安装和运行」从源码跑起来即可。

## 一、游戏简介

棋盘由 18 × 28 的格子组成，上面散布着许多箭头。每支箭头由若干连续格子组成
（蛇形箭身），头格朝向四个方向之一。玩家点击箭头：

- 如果**头格前方那条直线一路到棋盘边界**都没有别的箭头（也不包括自己的尾巴），
  这支箭头就沿着自己的朝向飞出棋盘、被消除；
- 如果前方有阻挡，箭头留在原地，并通过顶部提示条 + 生命值 -1 给出碰撞反馈；
- 每次误点消耗一条生命，3 条生命用完本关失败；
- 清空棋盘上全部箭头即通关，可以挑战下一关。

规则简单，但需要观察箭头之间的相互阻挡关系，找出正确的清除顺序。

## 二、游戏截图

| 开始界面 | 游戏界面 |
|---|---|
| ![开始界面](assets/home.png) | ![游戏界面](assets/game.png) |

| 通关界面 | 失败界面 |
|---|---|
| ![通关界面](assets/success.png) | ![失败界面](assets/failure.png) |

其他界面：

| 选择关卡 | 历史得分 |
|---|---|
| ![选择关卡](assets/level-select.png) | ![历史得分](assets/history.png) |

## 三、开发环境

| 项目 | 版本 / 说明 |
|---|---|
| 操作系统 | Windows 10 |
| Python | 3.12.10（3.10 以上均可） |
| 图形库 | pygame 2.6.1（唯一的第三方依赖） |
| 中文字体 | 取系统自带的微软雅黑 `msyh.ttc`，找不到时回退到 `pygame.font.SysFont` |
| 测试 | Python 标准库 `unittest`，无额外依赖 |

项目**不依赖任何外部图片、音效文件**：界面里的箭头、齿轮、爱心、时钟、辅助线、
Logo 图案都是用 `pygame.draw` 现场绘制的，所以克隆下来就能直接跑。

## 四、安装和运行

### 1. 最省事的方式（Windows）

双击项目根目录下的 **`run_python_game.bat`**。脚本会依次尝试：

1. 使用项目里的 `.venv\Scripts\python.exe`；
2. 回退到本机已知的 Python 解释器；
3. 再回退到 `PATH` 里的 `python`；

随后检查 `pygame` 是否已安装，缺少就自动执行 `pip install -r requirements.txt`，
最后启动游戏。若环境有问题，会打印中文提示并停住，不会一闪而过。

### 2. 命令行方式

```powershell
python -m pip install -r requirements.txt
python arrow_game.py
```

### 3. 使用虚拟环境（推荐，环境更干净）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe arrow_game.py
```

### 4. 环境自检

生成全部 5 个关卡并退出，用来确认依赖装好、关卡算法正常：

```powershell
python arrow_game.py --smoke-test
```

正常时逐关打印箭头数量和可解性，最后输出一行“自检通过”，进程返回 0。

### 5. 打包成可执行文件（可选）

不想装 Python 的电脑可以用 PyInstaller 打包成一个独立的 exe：

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name ArrowArrow arrow_game.py
```

产物在 `dist\ArrowArrow.exe`，双击即可运行（想换个名字直接重命名就行）。目标电脑
**不需要安装 Python 或 pygame**。

`--windowed` 表示不带控制台黑框；程序里已经对“没有控制台时 `sys.stdout` 为 `None`”
的情况做了兜底，所以打包成窗口程序不会刚启动就闪退。

打包产物（`build/`、`dist/`、`*.spec`、`*.exe`）都写在 `.gitignore` 里，不会进仓库。

## 五、游戏操作说明

全部操作只需鼠标左键，另有一个键盘快捷键。

| 操作 | 位置 | 说明 |
|---|---|---|
| 点击箭头 | 棋盘 | 箭头前方无阻挡则飞出消除；有阻挡则生命值 -1 并给出提示 |
| 拖动棋盘 | 棋盘空白处 | 放大后可以拖动查看 |
| 重玩 | 右上角「重玩」 | 当前关卡恢复初始布局，生命值回到 3 |
| 剩余箭头数 | 右上角「重玩」下方 | 实时显示棋盘上还剩多少支箭头 |
| 设置（齿轮） | 左上角 | 可以选关、重玩当前关卡或回到主界面 |
| 日间 / 夜间 | 左上角开关 | 切换界面配色 |
| 提示 | 底部左侧 | 高亮一支当前可以飞出的箭头 |
| 辅助线 | 底部右侧 | 显示网格线，方便判断行列 |
| 缩放 | 底部滑杆 / `−` `＋` | 在 0.75 ~ 1.25 倍之间缩放棋盘 |
| 关闭弹窗 | `Esc` | 快捷键关闭当前弹窗 |

## 六、关卡

| 关卡 | 箭头数量 | 说明 |
|---|---:|---|
| 第 1 关 | 58 | 熟悉「整条路径都会阻挡」的规则 |
| 第 2 关 | 79 | 增加同行同列的交叉观察 |
| 第 3 关 | 87 | 棋盘变密，需要先清出通道 |
| 第 4 关 | 99 | 蛇形箭头变长，自己的尾巴也会挡自己 |
| 第 5 关 | 136 | 最密的一关，几乎铺满棋盘 |

关卡不是手写的固定数据，而是由 `build_level()` 按种子程序化生成，生成过程中
用回溯搜索校验「一定存在完整清除顺序」，不可解的候选会被直接回滚丢弃，因此
**每一关都保证可以通关**。同一个种子生成的布局完全一致，方便复现和测试。

## 七、运行测试

```powershell
python -m unittest discover -s tests -v
```

共 69 项自动化测试，覆盖作业要求的 T01 ~ T06，以及路径检测的边界情况、关卡结构
合法性、通关 / 失败 / 重新开始的完整界面流程。测试使用 SDL 的 dummy 视频驱动，
**无窗口也能跑**，不会弹出游戏窗口。

```powershell
# 只跑规则层
python -m unittest tests.test_arrow_game.ArrowRulesTests -v
# 只跑界面流程
python -m unittest tests.test_arrow_game.ArrowPuzzleFlowTests -v
```

## 八、项目结构

```text
arrow-arrow-clone-python/
├── arrow_game.py            # 全部游戏代码（规则 + 关卡生成 + 界面）
├── tests/
│   └── test_arrow_game.py   # 69 项自动化测试
├── assets/                  # 界面截图与演示动图（README / 博客用）
├── requirements.txt         # 依赖清单（pygame==2.6.1）
├── run_python_game.bat      # Windows 双击启动器
├── BLOG.md                  # 作业博客正文（AIGC 使用记录、测试结果、PSP）
└── README.md
```

`arrow_game.py` 里各部分的对应关系：

| 内容 | 主要函数 / 类 |
|---|---|
| 箭头与游戏状态的数据结构 | `Arrow`、`GameState` |
| 路径检测 | `arrow_can_leave_from_occupied`、`can_arrow_leave`、`get_block_info` |
| 关卡生成与可解性校验 | `build_level`、`difficulty_profile`、`clone_level` |
| 计分与失误 | `calculate_score`、`consume_mistake`、`format_duration` |
| 界面与交互 | `ArrowPuzzle` |

## 九、关于 AIGC

本项目在开发过程中使用 **Codex** 辅助（需求拆解、代码骨架、界面排错、
关卡的自动校验思路、测试用例设计）。详细的协作记录、AI 做了什么、我做了哪些
修改，见 [BLOG.md](BLOG.md) 第四节「AIGC 使用过程」。

需要说明的是：AI 生成的代码经过逐行阅读、实际运行和自动化测试验证后才保留；
测试过程中还发现并修复了一个真实缺陷（超时判负后仍可点击导致棋盘卡死），
过程记录在同名博客里。

## 十、素材来源

- 代码：全部自己实现，未复制他人完整项目。
- 图形：全部用 `pygame.draw` 绘制，没有使用第三方图片。
- 音效：未使用。
- 字体：调用系统已安装的微软雅黑（`C:\Windows\Fonts\msyh.ttc`）。
- 玩法参考：微信小游戏《一箭又一箭》，仅参考核心玩法，未使用其任何素材或关卡。
