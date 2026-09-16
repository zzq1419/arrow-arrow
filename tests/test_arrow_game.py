"""一箭又一箭（Python / Pygame 复刻版）自动化测试。

测试对象是 ``arrow_game.py``。棋盘是 18 列 x 28 行的网格，每支箭头由若干
连续格子组成（蛇形），头格 ``arrow.path[-1]`` 沿 ``(dx, dy)`` 方向前进。
格子的坐标一律写成 ``(col, row)``。

测试分四层：

1. ``ArrowRulesTests``      纯路径检测规则，不需要窗口
2. ``LevelGenerationTests`` 生成关卡的结构合法性与可通关性
3. ``ArrowPuzzleFlowTests`` 用 SDL dummy 驱动真实游戏流程（开始 / 点击 / 通关 / 失败 / 重开）
4. ``CommandLineTests``     ``--smoke-test`` 命令行入口

运行::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 必须在 import pygame 之前设置，否则无显示器环境无法创建窗口。
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

import arrow_game as ag  # noqa: E402


# --------------------------------------------------------------------------
# 测试辅助
# --------------------------------------------------------------------------

COLS, ROWS = 18, 28
DIRECTIONS = {"R": (1, 0), "L": (-1, 0), "U": (0, -1), "D": (0, 1)}
COLOR = (240, 123, 105)


def make_arrow(cells, ident=0, direction=None):
    """构造一支箭头。``cells`` 为 ``[(col, row), ...]``，最后一格是头格。"""
    cells = [tuple(cell) for cell in cells]
    if len(cells) < 2:
        raise ValueError("箭头至少需要两个格子")
    if direction is None:
        (col_a, row_a), (col_b, row_b) = cells[-2], cells[-1]
        direction = ((col_b > col_a) - (col_b < col_a), (row_b > row_a) - (row_b < row_a))
    return ag.Arrow(ident, cells, direction[0], direction[1], COLOR)


def straight(head, length, direction, ident=0):
    """生成一支直线箭头。

    ``head`` 是头格坐标，箭身朝反方向铺开，所以 ``head`` 后方要有足够空间。
    ``direction`` 取 ``'R' / 'L' / 'U' / 'D'``。
    """
    dc, dr = DIRECTIONS[direction]
    col, row = head
    cells = [(col - dc * step, row - dr * step) for step in range(length - 1, -1, -1)]
    return make_arrow(cells, ident, (dc, dr))


def parse_board(lines, ident_offset=0):
    """把字符画转成单格箭头列表。

    ``.`` 和空格表示空地，``R/L/U/D`` 表示头朝右/左/上/下的箭头；字符所在的
    列就是头格，箭身朝相反方向多占一格，因此字符不能紧贴棋盘背面边缘。
    """
    arrows = []
    for row, line in enumerate(lines):
        for col, token in enumerate(line):
            if token in DIRECTIONS:
                dc, dr = DIRECTIONS[token]
                arrows.append(make_arrow([(col - dc, row - dr), (col, row)], ident_offset + len(arrows), (dc, dr)))
    return arrows


def occupied_of(arrows):
    return {cell for arrow in arrows for cell in arrow.cells}


def free_arrows(arrows, cols=COLS, rows=ROWS):
    occupied = occupied_of(arrows)
    return [a for a in arrows if ag.arrow_can_leave_from_occupied(a, occupied, cols, rows)]


def blocked_arrows(arrows, cols=COLS, rows=ROWS):
    occupied = occupied_of(arrows)
    return [a for a in arrows if not ag.arrow_can_leave_from_occupied(a, occupied, cols, rows)]


@functools.lru_cache(maxsize=None)
def level_template(number):
    """按 ``LEVEL_CONFIGS`` 生成一次关卡，多个测试复用，避免重复计算。"""
    return ag.build_level(ag.LEVEL_CONFIGS[number]["seeds"][0], number)


LEVEL_NUMBERS = tuple(sorted(ag.LEVEL_CONFIGS))


# --------------------------------------------------------------------------
# 一、纯规则层
# --------------------------------------------------------------------------

class ArrowRulesTests(unittest.TestCase):
    """路径检测、边界处理、失误扣减与计分。"""

    # -------- T01 / T02：前进方向的路径检测 --------

    def test_T01_clear_path_arrow_can_leave(self):
        """T01 前方无阻挡的箭头可以飞出。"""
        arrow = straight((2, 0), 3, "R")
        self.assertTrue(free_arrows([arrow]))

    def test_T02_classic_example_row_blocked_by_another_arrow(self):
        """T02 作业示例 ``→ . . ↑ .``：朝右的第一支被同行的箭头挡住。"""
        arrows = parse_board([
            " R...U ",
            "       ",
            "     R ",
        ])
        first, corner, last = arrows
        self.assertEqual((first.dx, first.dy), (1, 0))
        self.assertEqual(corner.path, [(5, 1), (5, 0)])
        self.assertFalse(ag.arrow_can_leave_from_occupied(first, occupied_of(arrows), 7, 3))
        # 最后一支朝右，右边没有箭头，可以飞出棋盘。
        self.assertTrue(ag.arrow_can_leave_from_occupied(last, occupied_of(arrows), 7, 3))

    def test_T02_block_info_reports_the_blocking_arrow(self):
        """T02 阻挡信息要能指出被谁挡住（用于碰撞提示文案）。"""
        arrows = parse_board([" R...U "])
        first, blocker = arrows
        info = ag.get_block_info(arrows, first, 7, 1)
        self.assertTrue(info["blocked"])
        self.assertIs(info["owner"], blocker)
        self.assertEqual(info["blocker"], (5, 0))
        self.assertEqual(info["cells"], [(2, 0), (3, 0), (4, 0)])

    def test_T02_blocker_far_away_with_blank_cells_still_blocks(self):
        """整条路径都要检查，不是只看相邻一格。"""
        head = straight((1, 5), 2, "R")
        far = straight((15, 5), 2, "L")
        self.assertFalse(ag.arrow_can_leave_from_occupied(head, occupied_of([head, far]), COLS, ROWS))

    def test_T02_arrow_behind_the_head_does_not_block(self):
        """头格后方的箭头不构成阻挡。"""
        head = straight((8, 5), 3, "R")
        behind = straight((3, 5), 3, "L")
        self.assertTrue(ag.arrow_can_leave_from_occupied(head, occupied_of([head, behind]), COLS, ROWS))

    def test_T02_other_row_and_column_do_not_block(self):
        """不在同一行/列上的箭头不构成阻挡。"""
        head = straight((2, 5), 3, "R")
        other_row = straight((12, 6), 3, "L")
        other_col = straight((5, 10), 3, "U")
        self.assertTrue(ag.arrow_can_leave_from_occupied(head, occupied_of([head, other_row, other_col]), COLS, ROWS))

    def test_T02_tail_of_the_same_arrow_blocks_its_own_head(self):
        """蛇形箭头：自己的尾巴落在头前方时同样算阻挡。"""
        # 螺旋形，头格 (1, 0) 朝左，射线上的 (0, 0) 属于这支箭头自己。
        spiral = make_arrow([(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0)])
        self.assertEqual((spiral.dx, spiral.dy), (-1, 0))
        self.assertFalse(ag.arrow_can_leave_from_occupied(spiral, occupied_of([spiral]), COLS, ROWS))
        info = ag.get_block_info([spiral], spiral, COLS, ROWS)
        self.assertTrue(info["blocked"])
        self.assertIs(info["owner"], spiral)

    def test_snake_body_any_cell_in_the_ray_blocks(self):
        """射线打到另一支箭头的中段（不是头格）也算阻挡。"""
        head = straight((1, 5), 2, "R")
        snake = make_arrow([(6, 5), (6, 6), (7, 6), (8, 6)], ident=1)  # 头在 (8, 6)，身体占了 (6, 5)
        self.assertFalse(ag.arrow_can_leave_from_occupied(head, occupied_of([head, snake]), COLS, ROWS))

    # -------- T03：边界处理 --------

    def test_T03_edge_arrows_facing_outward_leave_without_index_error(self):
        """T03 位于边缘且朝向棋盘外的箭头可以正常飞出，不发生越界错误。"""
        cases = [
            ("left", straight((0, 0), 2, "L")),
            ("right", straight((COLS - 1, 0), 2, "R")),
            ("up", straight((0, 0), 2, "U")),
            ("down", straight((0, ROWS - 1), 2, "D")),
        ]
        for index, (name, arrow) in enumerate(cases):
            arrow.id = index
            with self.subTest(edge=name, head=arrow.path[-1], direction=(arrow.dx, arrow.dy)):
                self.assertTrue(ag.arrow_can_leave_from_occupied(arrow, occupied_of([arrow]), COLS, ROWS))

    def test_T03_ray_stops_exactly_at_the_border(self):
        """紧贴边界的阻挡仍然生效，不能因为越界判断而漏判。"""
        head = straight((1, 0), 2, "R")
        edge = straight((16, 1), 2, "D", ident=1)
        info = ag.get_block_info([head, edge], head, COLS, ROWS)
        self.assertTrue(info["blocked"])
        self.assertEqual(info["blocker"], (16, 0))

    def test_ray_walks_to_the_border_when_nothing_is_inside(self):
        """没有被阻挡时，返回的路径要一直走到棋盘边界。"""
        arrow = straight((1, 3), 2, "R")
        info = ag.get_block_info([arrow], arrow, COLS, ROWS)
        self.assertFalse(info["blocked"])
        self.assertEqual(info["cells"][0], (2, 3))
        self.assertEqual(info["cells"][-1], (COLS - 1, 3))

    def test_can_arrow_leave_matches_the_occupied_set_version(self):
        """``can_arrow_leave`` 与底层函数结论一致。"""
        arrows = parse_board([" R...U ", "     R "])
        for arrow in arrows:
            self.assertEqual(
                ag.can_arrow_leave(arrows, arrow, 7, 2),
                ag.arrow_can_leave_from_occupied(arrow, occupied_of(arrows), 7, 2),
            )

    # -------- 失误次数与计分 --------

    def test_T05_consume_mistake_ends_the_game_at_zero_lives(self):
        """T05 三次失误后生命值归零并标记失败。"""
        game = ag.GameState(arrows=[], lives=3)
        self.assertTrue(ag.consume_mistake(game))
        self.assertTrue(ag.consume_mistake(game))
        self.assertEqual(game.lives, 1)
        self.assertFalse(ag.consume_mistake(game))
        self.assertEqual(game.lives, 0)
        self.assertTrue(game.dead)

    def test_consume_mistake_never_goes_below_zero(self):
        game = ag.GameState(arrows=[], lives=1)
        ag.consume_mistake(game)
        self.assertFalse(ag.consume_mistake(game))
        self.assertEqual(game.lives, 0)

    def test_T07_score_is_a_bounded_percentage(self):
        """T07 通关得分始终落在 0~100。"""
        perfect = ag.GameState(arrows=[], seconds_left=ag.MAX_SECONDS, lives=3)
        score = ag.calculate_score(perfect)
        self.assertEqual(score["total"], 100)
        self.assertEqual(score["elapsedSeconds"], 0)

        worst = ag.GameState(arrows=[], seconds_left=0, lives=0)
        self.assertEqual(ag.calculate_score(worst)["total"], 0)

        for seconds_left in range(0, ag.MAX_SECONDS + 1, 37):
            for lives in range(0, 4):
                value = ag.calculate_score(ag.GameState(arrows=[], seconds_left=seconds_left, lives=lives))
                self.assertGreaterEqual(value["total"], 0)
                self.assertLessEqual(value["total"], 100)
                self.assertEqual(value["elapsedSeconds"], ag.MAX_SECONDS - seconds_left)

    def test_score_drops_with_time_and_mistakes(self):
        slow = ag.calculate_score(ag.GameState(arrows=[], seconds_left=100, lives=3))
        fast = ag.calculate_score(ag.GameState(arrows=[], seconds_left=380, lives=3))
        careless = ag.calculate_score(ag.GameState(arrows=[], seconds_left=380, lives=1))
        self.assertGreater(fast["timeBonus"], slow["timeBonus"])
        self.assertGreater(fast["total"], careless["total"])

    def test_format_duration_pads_to_mm_ss(self):
        self.assertEqual(ag.format_duration(0), "00:00")
        self.assertEqual(ag.format_duration(9), "00:09")
        self.assertEqual(ag.format_duration(75), "01:15")
        self.assertEqual(ag.format_duration(ag.MAX_SECONDS), "07:00")

    def test_rgb_and_rgba_accept_hex_and_tuple(self):
        self.assertEqual(ag.rgb("#f5bf27"), (245, 191, 39))
        self.assertEqual(ag.rgb((1, 2, 3)), (1, 2, 3))
        self.assertEqual(ag.rgba("#000000", 128), (0, 0, 0, 128))

    def test_hash_rand_is_deterministic_and_bounded(self):
        first, second = ag.hash_rand(101), ag.hash_rand(101)
        self.assertEqual([first() for _ in range(20)], [second() for _ in range(20)])
        self.assertTrue(all(0.0 <= ag.hash_rand(7)() < 1.0 for _ in range(50)))
        self.assertNotEqual(ag.hash_rand(1)(), ag.hash_rand(2)())


# --------------------------------------------------------------------------
# 二、关卡生成
# --------------------------------------------------------------------------

class LevelGenerationTests(unittest.TestCase):
    """生成的关卡必须结构合法、四方向齐全而且可以通关。"""

    def test_at_least_three_levels_exist(self):
        """作业要求至少 3 个关卡，本项目提供 5 个。"""
        self.assertGreaterEqual(len(LEVEL_NUMBERS), 3)
        self.assertEqual(list(LEVEL_NUMBERS), [1, 2, 3, 4, 5])

    def test_T04_every_level_is_solvable(self):
        """T04 每一关都存在完整的清除顺序（可以通关）。"""
        for number in LEVEL_NUMBERS:
            with self.subTest(level=number):
                level = level_template(number)
                profile = level.profile
                self.assertTrue(profile["solved"], f"第 {number} 关无解")
                self.assertEqual(len(profile["order"]), len(level.arrows))
                self.assertEqual(sorted(profile["order"]), sorted(a.id for a in level.arrows))
                self.assertGreater(len(level.arrows), 0)

    def test_T08_all_four_directions_are_used(self):
        """T08 上、下、左、右四种方向的箭头都要出现。"""
        for number in LEVEL_NUMBERS:
            with self.subTest(level=number):
                directions = {(a.dx, a.dy) for a in level_template(number).arrows}
                self.assertEqual(
                    directions,
                    {(1, 0), (-1, 0), (0, 1), (0, -1)},
                    f"第 {number} 关方向不齐全: {sorted(directions)}",
                )

    def test_arrows_never_overlap_within_a_level(self):
        for number in LEVEL_NUMBERS:
            with self.subTest(level=number):
                level = level_template(number)
                cells = [cell for arrow in level.arrows for cell in arrow.cells]
                self.assertEqual(len(cells), len(set(cells)))

    def test_paths_are_contiguous_axis_aligned_and_inside_the_board(self):
        for number in LEVEL_NUMBERS:
            level = level_template(number)
            for arrow in level.arrows:
                with self.subTest(level=number, arrow=arrow.id):
                    self.assertGreaterEqual(len(arrow.path), 2)
                    self.assertEqual(len(set(arrow.path)), len(arrow.path))
                    for col, row in arrow.path:
                        self.assertTrue(0 <= col < level.cols)
                        self.assertTrue(0 <= row < level.rows)
                    for (col_a, row_a), (col_b, row_b) in zip(arrow.path, arrow.path[1:]):
                        self.assertIn((abs(col_b - col_a), abs(row_b - row_a)), ((1, 0), (0, 1)))
                        self.assertNotEqual(col_a == col_b, row_a == row_b)
                    (col_a, row_a), (col_b, row_b) = arrow.path[-2], arrow.path[-1]
                    self.assertEqual((arrow.dx, arrow.dy), (col_b - col_a, row_b - row_a))

    def test_generation_is_deterministic(self):
        """同一个种子必须生成同一个布局（可复现，便于测试和试玩）。"""
        first = ag.build_level(ag.LEVEL_CONFIGS[1]["seeds"][0], 1)
        second = ag.build_level(ag.LEVEL_CONFIGS[1]["seeds"][0], 1)
        self.assertEqual([a.path for a in first.arrows], [a.path for a in second.arrows])
        self.assertEqual([(a.dx, a.dy) for a in first.arrows], [(a.dx, a.dy) for a in second.arrows])

    def test_arrow_count_grows_with_the_level_number(self):
        counts = [len(level_template(number).arrows) for number in LEVEL_NUMBERS]
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(counts[-1], counts[0])

    def test_every_level_has_a_legal_first_move(self):
        for number in LEVEL_NUMBERS:
            level = level_template(number)
            self.assertTrue(free_arrows(level.arrows, level.cols, level.rows), f"第 {number} 关开局没有可点箭头")

    def test_greedily_clearing_free_arrows_empties_every_level(self):
        """一直点“当前可以飞出”的箭头，最终能清空棋盘。"""
        for number in LEVEL_NUMBERS:
            with self.subTest(level=number):
                total = len(level_template(number).arrows)
                remaining = list(level_template(number).arrows)
                steps = 0
                while remaining:
                    candidate = free_arrows(remaining, COLS, ROWS)
                    self.assertTrue(candidate, f"第 {number} 关在第 {steps} 步卡死")
                    remaining.remove(candidate[0])
                    steps += 1
                self.assertEqual(steps, total)

    def test_difficulty_profile_reports_bottlenecks(self):
        level = level_template(3)
        profile = level.profile
        self.assertGreaterEqual(profile["bottlenecks"], 0)
        self.assertGreaterEqual(profile["unique_steps"], 0)
        self.assertLessEqual(profile["unique_steps"], len(level.arrows))
        self.assertEqual(len(profile["legal_counts"]), len(level.arrows))

    def test_T06_clone_level_restores_the_initial_state(self):
        """T06 克隆/重开得到的是一份全新的初始状态。"""
        template = level_template(1)
        used = ag.clone_level(template)
        used.lives = 1
        used.dead = True
        used.complete = True
        used.seconds_left = 5
        used.busy = True
        used.arrows = used.arrows[:3]
        used.arrows[0].path.append((0, 0))
        used.arrows[0].moving = True

        restarted = ag.clone_level(template)
        self.assertEqual(restarted.lives, 3)
        self.assertFalse(restarted.dead)
        self.assertFalse(restarted.complete)
        self.assertFalse(restarted.busy)
        self.assertEqual(restarted.seconds_left, ag.MAX_SECONDS)
        self.assertEqual(len(restarted.arrows), len(template.arrows))
        self.assertEqual([a.path for a in restarted.arrows], [a.path for a in template.arrows])
        self.assertFalse(any(a.moving for a in restarted.arrows))

    def test_clone_level_does_not_alias_the_template_arrows(self):
        template = level_template(1)
        clone = ag.clone_level(template)
        clone.arrows[0].path.append((0, 0))
        clone.arrows[0].color = (0, 0, 0)
        self.assertNotIn((0, 0), template.arrows[0].path)
        self.assertEqual(template.arrows[0].color, ag.rgb(ag.COLORS[0]))


# --------------------------------------------------------------------------
# 三、真实游戏流程（SDL dummy 无窗口驱动 ArrowPuzzle）
# --------------------------------------------------------------------------

class ArrowPuzzleFlowTests(unittest.TestCase):
    """通过 ``ArrowPuzzle`` 的公开方法驱动真实流程，验证作业要求的交互。"""

    @classmethod
    def setUpClass(cls):
        cls.templates = {number: level_template(number) for number in LEVEL_NUMBERS}

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.app = ag.ArrowPuzzle()
        # 得分历史写到临时目录，避免污染仓库里的 score_history.json
        self.tmpdir = tempfile.TemporaryDirectory(prefix="arrow-game-tests-")
        self.app.history_path = Path(self.tmpdir.name) / "score_history.json"
        self.app.level_cache = dict(self.templates)

    def tearDown(self):
        self.tmpdir.cleanup()

    # -------- 通用动作 --------

    def start_level(self, number=1):
        self.app.current_level = number
        self.app.start_game()
        return self.app.game

    def canvas_to_design(self, position):
        """把棋盘画布坐标换算成设计稿坐标（点击处理使用的坐标系）。"""
        rect = self.app.board_screen_rect()
        return (
            rect.left + position[0] / ag.CANVAS_W * rect.width,
            rect.top + position[1] / ag.CANVAS_H * rect.height,
        )

    def click_cell(self, cell):
        """按真实鼠标路径点击某个格子的中心。"""
        metrics = self.app.board_metrics()
        self.app.handle_mouse_down(self.canvas_to_design(self.app.point_for(cell, metrics)))

    def click_arrow(self, arrow):
        self.click_cell(arrow.path[-1])

    def click_design(self, position):
        self.app.handle_mouse_down(position)

    def inject_state(self, arrows, lives=3, level_number=1):
        """用一批自造的箭头直接替换当前关卡，模拟一个受控的小棋盘。"""
        state = ag.GameState(arrows=list(arrows), cols=COLS, rows=ROWS, level_number=level_number, lives=lives)
        self.app.game = state
        self.app.screen_name = "game"
        self.app.modal = None  # 上一局通关可能留下弹窗，这里显式清掉
        return state

    def finish_animation(self):
        """让当前飞出的箭头立刻走完动画（同时保持计时器基本不变）。"""
        now = pygame.time.get_ticks()
        self.app.game.started_at = now - 1000
        for arrow in self.app.game.arrows:
            if arrow.moving:
                arrow.move_started = now - arrow.duration
        self.app.update_game(now)

    def current_free(self):
        game = self.app.game
        return free_arrows(game.arrows, game.cols, game.rows)

    def current_blocked(self):
        game = self.app.game
        return blocked_arrows(game.arrows, game.cols, game.rows)

    def clear_level(self):
        """贪心清空当前关卡，返回点击次数。"""
        clicks = 0
        while self.app.game.arrows:
            candidates = self.current_free()
            self.assertTrue(candidates, "没有可以点击的箭头，关卡卡死")
            self.click_arrow(candidates[0])
            self.assertTrue(self.app.game.busy, "合法点击后应该进入飞出动画")
            self.finish_animation()
            clicks += 1
        return clicks

    # -------- 界面骨架 --------

    def test_home_screen_starts_the_game(self):
        self.assertEqual(self.app.screen_name, "home")
        self.assertIsNone(self.app.game)
        self.click_design((296, 859))  # “开始游戏”
        self.assertEqual(self.app.screen_name, "game")
        self.assertEqual(self.app.game.level_number, 1)
        self.assertEqual(self.app.game.lives, 3)

    def test_home_screen_opens_level_selection_and_switches_level(self):
        self.click_design((205, 946))  # “选择关卡”
        self.assertEqual(self.app.modal, "level-selection")
        self.click_design((292, 525))  # 关卡按钮 3
        self.assertIsNone(self.app.modal)
        self.assertEqual(self.app.current_level, 3)
        self.assertEqual(self.app.game.level_number, 3)
        self.assertEqual(self.app.screen_name, "game")

    def test_home_screen_opens_history_modal(self):
        self.click_design((387, 946))  # “历史得分”
        self.assertEqual(self.app.modal, "history")
        self.click_design((296, 694))  # “知道了”
        self.assertIsNone(self.app.modal)

    def test_settings_modal_can_restart_and_go_home(self):
        self.start_level(1)
        self.click_design((56, 76))  # 齿轮
        self.assertEqual(self.app.modal, "settings")
        self.click_design((213, 625))  # “重玩当前关卡”
        self.assertIsNone(self.app.modal)
        self.assertEqual(self.app.screen_name, "game")
        self.click_design((56, 76))
        self.click_design((378, 625))  # “回到主界面”
        self.assertEqual(self.app.screen_name, "home")
        self.assertIsNone(self.app.game)

    def test_escape_closes_the_modal(self):
        self.start_level(1)
        self.app.show_settings()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        self.app.process_events()
        self.assertIsNone(self.app.modal)

    def test_dark_mode_toggle_and_toast(self):
        game = self.start_level(1)
        before = self.app.dark_mode
        self.click_design((156, 76))  # 日间/夜间开关
        self.assertNotEqual(self.app.dark_mode, before)
        self.assertTrue(self.app.toast_text)
        self.assertIs(self.app.game, game)  # 开关热区不应误触“重玩”

    def test_hint_button_highlights_a_playable_arrow(self):
        game = self.start_level(1)
        self.click_design((57, 999))  # “提示”
        highlighted = [arrow for arrow in game.arrows if arrow.hint]
        self.assertEqual(len(highlighted), 1)
        self.assertIn(highlighted[0], self.current_free())

    def test_guides_toggle(self):
        self.start_level(1)
        self.assertFalse(self.app.guides)
        self.click_design((534, 999))  # “辅助线”
        self.assertTrue(self.app.guides)
        self.click_design((534, 999))
        self.assertFalse(self.app.guides)

    def test_zoom_controls_stay_inside_the_allowed_range(self):
        self.start_level(1)
        self.click_design((487, 991))  # ＋
        self.assertGreater(self.app.zoom, 1.0)
        self.assertLessEqual(self.app.zoom, ag.MAX_ZOOM)
        for _ in range(20):
            self.click_design((112, 991))  # −
        self.assertAlmostEqual(self.app.zoom, ag.MIN_ZOOM)
        for _ in range(30):
            self.click_design((487, 991))
        self.assertAlmostEqual(self.app.zoom, ag.MAX_ZOOM)

    def test_zoom_slider_maps_x_to_zoom(self):
        self.start_level(1)
        self.app.zoom_from_x(135)
        self.assertAlmostEqual(self.app.zoom, ag.MIN_ZOOM)
        self.app.zoom_from_x(457)
        self.assertAlmostEqual(self.app.zoom, ag.MAX_ZOOM)
        self.app.zoom_from_x(0)  # 越界输入要被夹紧
        self.assertAlmostEqual(self.app.zoom, ag.MIN_ZOOM)
        self.app.zoom_from_x(9999)
        self.assertAlmostEqual(self.app.zoom, ag.MAX_ZOOM)

    def test_three_dot_menu_button_has_been_removed(self):
        """三个点的菜单按钮已下线，原位置再点击不应弹出任何弹窗。"""
        self.start_level(1)
        self.assertIsNone(self.app.modal)
        self.click_design((531, 75))  # 原来是 “•••” 的位置
        self.assertIsNone(self.app.modal)

    def test_top_right_restart_button_restores_the_level(self):
        """“重玩”已挪到顶栏右上角，点击后关卡回到初始状态。"""
        game = self.start_level(2)
        original = len(game.arrows)
        dark_before = self.app.dark_mode
        self.click_arrow(self.current_free()[0])
        self.finish_animation()
        self.assertLess(len(game.arrows), original)
        self.click_design((528, 66))  # 右上角 “重玩”
        self.assertIsNot(self.app.game, game)
        self.assertEqual(len(self.app.game.arrows), original)
        self.assertEqual(self.app.game.lives, 3)
        self.assertEqual(self.app.dark_mode, dark_before)  # 不应误触日夜开关

    def test_board_metrics_fit_inside_the_canvas(self):
        self.start_level(5)
        pad_x, pad_y, cell, width, height = self.app.board_metrics()
        self.assertGreater(cell, 0)
        self.assertLessEqual(pad_x + width, ag.CANVAS_W + 0.001)
        self.assertLessEqual(pad_y + height, ag.CANVAS_H + 0.001)

    # -------- T01 / T02 / T03：点击与路径 --------

    def test_T01_clicking_a_free_arrow_removes_it(self):
        """T01 点击前方无阻挡的箭头：箭头飞出棋盘并消失。"""
        game = self.start_level(1)
        target = self.current_free()[0]
        before = len(game.arrows)

        self.click_arrow(target)
        self.assertTrue(target.moving, "应该开始飞出动画")
        self.assertTrue(game.busy)
        self.assertEqual(target.progress, 0.0)

        self.finish_animation()
        self.assertNotIn(target, game.arrows)
        self.assertEqual(len(game.arrows), before - 1)
        self.assertFalse(game.busy)
        self.assertEqual(game.lives, 3)

    def test_T02_clicking_a_blocked_arrow_costs_one_life_and_keeps_it(self):
        """T02 点击前方有阻挡的箭头：箭头不消失，失误次数减 1。"""
        game = self.start_level(1)
        target = self.current_blocked()[0]
        before = len(game.arrows)

        self.click_arrow(target)
        self.assertEqual(game.lives, 2)
        self.assertEqual(len(game.arrows), before)
        self.assertIn(target, game.arrows)
        self.assertFalse(target.moving)
        self.assertFalse(game.busy)
        self.assertFalse(game.dead)
        # 碰撞反馈：给出提示文字
        self.assertIn("生命值 -1", self.app.toast_text)
        self.assertIn("2", self.app.toast_text)

    def test_T02_toast_explains_a_self_tail_collision(self):
        """碰撞反馈要区分“自己的尾巴”和“别的箭头”。"""
        spiral = make_arrow([(0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0)])
        state = self.inject_state([spiral])
        self.click_arrow(spiral)
        self.assertFalse(spiral.moving)
        self.assertEqual(state.lives, 2)
        self.assertIn("尾巴", self.app.toast_text)

    def test_clicking_an_empty_cell_is_ignored(self):
        game = self.start_level(1)
        occupied = occupied_of(game.arrows)
        empty = None
        for col in range(game.cols):
            for row in range(game.rows):
                neighbours = {(col + dc, row + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
                if not (neighbours & occupied):
                    empty = (col, row)
                    break
            if empty:
                break
        self.assertIsNotNone(empty, "关卡太密，找不到空格")
        self.click_cell(empty)
        self.assertEqual(game.lives, 3)
        self.assertFalse(game.busy)

    def test_T03_clicking_an_edge_arrow_facing_outward_removes_it(self):
        """T03 边缘且朝向棋盘外的箭头正常消失，不发生越界错误。"""
        cases = [
            ("left", straight((0, 0), 2, "L")),
            ("right", straight((COLS - 1, 0), 2, "R")),
            ("up", straight((0, 0), 2, "U")),
            ("down", straight((0, ROWS - 1), 2, "D")),
        ]
        for name, arrow in cases:
            with self.subTest(edge=name):
                state = self.inject_state([arrow])
                self.click_arrow(arrow)
                self.assertTrue(arrow.moving)
                self.finish_animation()
                self.assertEqual(state.arrows, [])

    def test_hit_test_selects_the_arrow_under_the_cursor(self):
        game = self.start_level(2)
        metrics = self.app.board_metrics()
        for arrow in game.arrows[:15]:
            with self.subTest(arrow=arrow.id):
                self.assertEqual(self.app.hit_test(*self.app.point_for(arrow.path[-1], metrics)), arrow)

    def test_hit_test_returns_none_outside_the_board(self):
        self.start_level(1)
        self.assertIsNone(self.app.hit_test(-50, -50))
        self.assertIsNone(self.app.hit_test(ag.CANVAS_W + 50, ag.CANVAS_H + 50))

    def test_a_flying_arrow_cannot_be_clicked_again(self):
        game = self.start_level(1)
        target = self.current_free()[0]
        metrics = self.app.board_metrics()
        self.click_arrow(target)
        self.assertTrue(target.moving)
        self.assertIsNone(self.app.hit_test(*self.app.point_for(target.path[-1], metrics)))

        other = next(arrow for arrow in self.current_free() if arrow is not target)
        self.click_arrow(other)
        self.assertFalse(other.moving, "飞出动画期间不应该再接受点击")
        self.assertFalse(game.dead)

    def test_arrow_route_flies_out_of_the_board(self):
        game = self.start_level(1)
        target = self.current_free()[0]
        route, distance = self.app.build_snake_route(target)
        self.assertEqual(route[: len(target.path)], [(float(col), float(row)) for col, row in target.path])
        last_col, last_row = route[-1]
        self.assertTrue(last_col < 0 or last_col >= game.cols or last_row < 0 or last_row >= game.rows)
        self.assertGreater(distance, len(target.path))
        self.assertEqual(len(route), len(target.path) + distance)

    # -------- T04：通关与关卡切换 --------

    def test_T04_clearing_the_board_shows_success_and_advances(self):
        """T04 清空本关后显示通关，并且可以进入下一关。"""
        game = self.start_level(1)
        total = len(game.arrows)
        clicks = self.clear_level()
        self.assertEqual(clicks, total)
        self.assertTrue(game.complete)
        self.assertEqual(self.app.modal, "success")
        self.assertIsNotNone(game.score)
        self.assertGreaterEqual(game.score["total"], 0)
        self.assertLessEqual(game.score["total"], 100)
        self.assertIn("第 1 关完成", self.app.modal_copy)

        self.click_design((296, 587))  # “挑战下一关”
        self.assertIsNone(self.app.modal)
        self.assertEqual(self.app.current_level, 2)
        self.assertEqual(self.app.game.level_number, 2)
        self.assertEqual(self.app.game.lives, 3)
        self.assertFalse(self.app.game.complete)
        self.assertEqual(len(self.app.game.arrows), len(self.templates[2].arrows))

    def test_T04_success_modal_go_home_button(self):
        self.start_level(1)
        self.clear_level()
        self.click_design((185, 587))  # “回到主界面”
        self.assertEqual(self.app.screen_name, "home")
        self.assertIsNone(self.app.game)

    def test_T04_last_level_wraps_back_to_the_first(self):
        self.start_level(5)
        self.clear_level()
        self.assertEqual(self.app.modal_next_text, "再挑战第1关")
        self.click_design((296, 587))
        self.assertEqual(self.app.current_level, 1)

    def test_success_records_a_history_entry(self):
        self.start_level(1)
        self.clear_level()
        records = self.app.history()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["level"], 1)
        self.assertEqual(records[0]["lives"], 3)
        saved = json.loads(self.app.history_path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["level"], 1)
        self.assertIn("score", saved[0])

    def test_history_tolerates_a_broken_file(self):
        self.app.history_path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.app.history(), [])
        self.app.history_path.write_text('{"a": 1}', encoding="utf-8")
        self.assertEqual(self.app.history(), [])

    def test_clicks_are_ignored_after_the_level_is_cleared(self):
        game = self.start_level(1)
        self.clear_level()
        lives_before = game.lives
        self.click_design((296, 400))  # 棋盘区域
        self.assertEqual(game.lives, lives_before)
        self.assertFalse(game.busy)

    # -------- T05：失败与重新开始 --------

    def test_T05_running_out_of_lives_shows_failure(self):
        """T05 失误次数耗尽：显示失败并允许重新开始。"""
        game = self.start_level(1)
        for expected_lives in (2, 1):
            self.click_arrow(self.current_blocked()[0])
            self.assertEqual(game.lives, expected_lives)
            self.assertFalse(game.dead)
        self.click_arrow(self.current_blocked()[0])
        self.assertEqual(game.lives, 0)
        self.assertTrue(game.dead)
        self.assertEqual(self.app.modal, "failure")
        self.assertIn("生命值都用完了", self.app.modal_copy)

        self.click_design((213, 622))  # “重玩当前关卡”
        self.assertIsNone(self.app.modal)
        self.assertEqual(self.app.game.lives, 3)
        self.assertFalse(self.app.game.dead)
        self.assertEqual(len(self.app.game.arrows), len(self.templates[1].arrows))

    def test_T05_failure_modal_go_home_button(self):
        self.start_level(1)
        for _ in range(3):
            self.click_arrow(self.current_blocked()[0])
        self.assertTrue(self.app.game.dead)
        self.click_design((378, 622))  # “回到主界面”
        self.assertEqual(self.app.screen_name, "home")
        self.assertIsNone(self.app.game)

    def test_T05_blocked_clicks_never_touch_the_board(self):
        """失败前的每次误点都只扣失误次数，棋盘保持不变。"""
        game = self.start_level(1)
        before = sorted(tuple(a.path) for a in game.arrows)
        for _ in range(3):
            self.click_arrow(self.current_blocked()[0])
        self.assertEqual(sorted(tuple(a.path) for a in game.arrows), before)

    def test_T06_restart_button_restores_the_level(self):
        """T06 游戏进行中重新开始：箭头布局和失误次数恢复。"""
        game = self.start_level(1)
        original = [list(arrow.path) for arrow in game.arrows]

        # 先飞掉 3 支、再失误 1 次，制造“进度被破坏”的局面
        for _ in range(3):
            self.click_arrow(self.current_free()[0])
            self.finish_animation()
        self.click_arrow(self.current_blocked()[0])
        self.assertEqual(game.lives, 2)
        self.assertLess(len(game.arrows), len(original))

        self.click_design((528, 66))  # 右上角 “重玩”按钮
        restarted = self.app.game
        self.assertIsNot(game, restarted)
        self.assertEqual(restarted.lives, 3)
        self.assertEqual(restarted.seconds_left, ag.MAX_SECONDS)
        self.assertEqual([list(arrow.path) for arrow in restarted.arrows], original)
        self.assertFalse(restarted.busy)
        self.assertFalse(any(arrow.moving for arrow in restarted.arrows))
        self.assertFalse(restarted.dead)
        self.assertIsNone(self.app.modal)

    def test_T06_restart_after_failure_then_win(self):
        """重开之后关卡依然可以通关。"""
        self.start_level(1)
        for _ in range(3):
            self.click_arrow(self.current_blocked()[0])
        self.assertTrue(self.app.game.dead)
        self.app.start_game()
        self.clear_level()
        self.assertTrue(self.app.game.complete)
        self.assertEqual(self.app.modal, "success")

    def test_restart_clears_momentary_style_state(self):
        self.start_level(1)
        self.app.zoom = ag.MAX_ZOOM
        self.app.guides = True
        self.click_arrow(self.current_free()[0])
        self.finish_animation()
        self.app.start_game()
        self.assertAlmostEqual(self.app.zoom, 1.0)
        self.assertFalse(self.app.guides)
        self.assertEqual(self.app.game.seconds_left, ag.MAX_SECONDS)

    # -------- 计时与失败分支 --------

    def test_timer_runs_down_and_shows_the_timeout_modal(self):
        game = self.start_level(1)
        now = pygame.time.get_ticks()
        game.started_at = now - 10_000
        self.app.update_game(now)
        self.assertEqual(game.seconds_left, ag.MAX_SECONDS - 10)

        game.started_at = now - (ag.MAX_SECONDS + 5) * 1000
        self.app.update_game(now)
        self.assertEqual(game.seconds_left, 0)
        self.assertTrue(game.dead)
        self.assertEqual(self.app.modal, "generic")

    def test_clicking_the_board_after_a_timeout_does_not_freeze_the_game(self):
        """回归测试：超时判负后箭头不应该还能被“射出”，否则棋盘会永久卡死。"""
        game = self.start_level(1)
        now = pygame.time.get_ticks()
        game.started_at = now - (ag.MAX_SECONDS + 5) * 1000
        self.app.update_game(now)
        self.assertTrue(game.dead)

        self.click_design((296, 629))  # 关闭“时间到啦”弹窗
        self.assertIsNone(self.app.modal)

        target = self.current_free()[0]
        self.click_arrow(target)
        self.assertFalse(game.busy, "已经判负的关卡不应该进入飞出状态")
        self.assertFalse(target.moving)
        self.assertIn(target, game.arrows)

    def test_shoot_is_a_no_op_without_a_game(self):
        self.app.shoot(straight((2, 0), 2, "R"))
        self.assertIsNone(self.app.game)


# --------------------------------------------------------------------------
# 四、命令行入口
# --------------------------------------------------------------------------

class CommandLineTests(unittest.TestCase):
    def test_smoke_test_builds_every_level_and_exits_zero(self):
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        result = subprocess.run(
            [sys.executable, str(ROOT / "arrow_game.py"), "--smoke-test"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
