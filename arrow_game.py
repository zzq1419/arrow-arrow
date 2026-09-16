"""一箭又一箭 · Python / Pygame 复刻版

This is a standalone port of the browser build in ../arrow-arrow-clone.
The original web project is intentionally left untouched.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pygame


DESIGN_W, DESIGN_H = 592, 1050
CANVAS_W, CANVAS_H = 420, 560
FPS = 60
MAX_SECONDS = 420
MIN_ZOOM, MAX_ZOOM = 0.75, 1.25
BOARD_RENDER_SCALE = 3

COLORS = ["#f5bf27", "#f07b69", "#8b7bdf", "#f38bc0", "#6cd0bb", "#75b2e5", "#89cf47", "#e992b9"]
LEVEL_CONFIGS = {
    1: dict(seeds=[101], base_arrows=24, min_length=2, length_span=3, extension_target=170, filler_target=230),
    2: dict(seeds=[211], base_arrows=38, min_length=2, length_span=4, extension_target=240, filler_target=305),
    3: dict(seeds=[317], base_arrows=54, min_length=3, length_span=4, extension_target=300, filler_target=365),
    4: dict(seeds=[421], base_arrows=70, min_length=3, length_span=5, extension_target=350, filler_target=410),
    5: dict(seeds=[53], base_arrows=88, min_length=3, length_span=5, extension_target=390, filler_target=504),
}


def rgb(value: str | tuple[int, int, int]) -> tuple[int, int, int]:
    if isinstance(value, tuple):
        return value
    value = value.removeprefix("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def rgba(value: str | tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (*rgb(value), alpha)


def hash_rand(seed: int):
    """Match the browser's small deterministic hashRand function."""
    mask = 0xFFFFFFFF
    state = (seed + 0x6D2B79F5) & mask

    def rand() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & mask
        value = (((state ^ (state >> 15)) * (1 | state)) & mask)
        value ^= (value + ((((value ^ (value >> 7)) * (61 | value)) & mask))) & mask
        return ((value ^ (value >> 14)) & mask) / 4294967296

    return rand


@dataclass
class Arrow:
    id: int
    path: list[tuple[int, int]]
    dx: int
    dy: int
    color: tuple[int, int, int]
    progress: float = 0.0
    moving: bool = False
    hint: bool = False
    hint_until: int = 0
    route: list[tuple[float, float]] | None = None
    move_distance: int = 0
    move_started: int = 0
    duration: int = 0

    @property
    def cells(self) -> list[tuple[int, int]]:
        return self.path


@dataclass
class GameState:
    arrows: list[Arrow]
    cols: int = 18
    rows: int = 28
    level_number: int = 1
    seconds_left: int = MAX_SECONDS
    lives: int = 3
    complete: bool = False
    dead: bool = False
    busy: bool = False
    started_at: int = 0
    score: dict | None = None


def key_for(cell: tuple[int, int]) -> tuple[int, int]:
    return cell


def arrow_can_leave_from_occupied(arrow: Arrow, occupied: set[tuple[int, int]], cols: int, rows: int) -> bool:
    head_col, head_row = arrow.path[-1]
    col, row = head_col + arrow.dx, head_row + arrow.dy
    while 0 <= col < cols and 0 <= row < rows:
        if (col, row) in occupied:
            return False
        col += arrow.dx
        row += arrow.dy
    return True


def can_arrow_leave(arrows: Iterable[Arrow], arrow: Arrow, cols: int, rows: int) -> bool:
    occupied: set[tuple[int, int]] = set()
    for other in arrows:
        occupied.update(other.cells)
    return arrow_can_leave_from_occupied(arrow, occupied, cols, rows)


def get_block_info(arrows: Iterable[Arrow], arrow: Arrow, cols: int, rows: int) -> dict:
    occupied: dict[tuple[int, int], Arrow] = {}
    for owner in arrows:
        for cell in owner.cells:
            occupied[cell] = owner
    head_col, head_row = arrow.path[-1]
    col, row = head_col + arrow.dx, head_row + arrow.dy
    cells: list[tuple[int, int]] = []
    while 0 <= col < cols and 0 <= row < rows:
        if (col, row) in occupied:
            return {"blocked": True, "cells": cells, "blocker": (col, row), "owner": occupied[(col, row)]}
        cells.append((col, row))
        col += arrow.dx
        row += arrow.dy
    return {"blocked": False, "cells": cells, "blocker": None, "owner": None}


def difficulty_profile(level: GameState) -> dict:
    remaining = list(level.arrows)
    occupied = {cell for arrow in remaining for cell in arrow.cells}
    legal_counts: list[int] = []
    order: list[int] = []
    while remaining:
        legal = [arrow for arrow in remaining if arrow_can_leave_from_occupied(arrow, occupied, level.cols, level.rows)]
        legal_counts.append(len(legal))
        if not legal:
            return dict(solved=False, legal_counts=legal_counts, order=order, bottlenecks=0, unique_steps=0)
        selected = legal[0]
        order.append(selected.id)
        remaining.remove(selected)
        for cell in selected.cells:
            occupied.discard(cell)
    return dict(
        solved=True,
        legal_counts=legal_counts,
        order=order,
        bottlenecks=sum(count <= 2 for count in legal_counts),
        unique_steps=sum(count == 1 for count in legal_counts),
    )


def build_level(seed: int = 5, level_number: int = 5) -> GameState:
    config = LEVEL_CONFIGS.get(level_number, LEVEL_CONFIGS[5])
    rand = hash_rand(seed)
    arrows: list[Arrow] = []
    occupied: set[tuple[int, int]] = set()
    line_directions: dict[tuple[str, int], int] = {}
    head_line_directions: dict[tuple[str, int], int] = {}
    cols, rows = 18, 28
    horizontal_directions = [1 if rand() < .5 else -1 for _ in range(rows)]
    vertical_directions = [1 if rand() < .5 else -1 for _ in range(cols)]

    def collect_line_directions(path: list[tuple[int, int]]):
        local: dict[tuple[str, int], int] = {}
        for before, current in zip(path, path[1:]):
            horizontal = before[1] == current[1]
            line_key = ("h" if horizontal else "v", current[1] if horizontal else current[0])
            direction = (1 if current[0] > before[0] else -1) if horizontal else (1 if current[1] > before[1] else -1)
            previous = local.get(line_key, line_directions.get(line_key))
            if previous and previous != direction:
                return None
            local[line_key] = direction
        return local

    def add_arrow(path: list[tuple[int, int]]) -> bool:
        if len(path) < 2:
            return False
        for before, current in zip(path, path[1:]):
            dx = (current[0] > before[0]) - (current[0] < before[0])
            dy = (current[1] > before[1]) - (current[1] < before[1])
            if dy == 0 and dx != horizontal_directions[current[1]]:
                return False
            if dx == 0 and dy != vertical_directions[current[0]]:
                return False
        path_keys = set(path)
        if len(path_keys) != len(path) or any(not (0 <= col < cols and 0 <= row < rows) for col, row in path):
            return False
        if path_keys & occupied:
            return False
        local_lines = collect_line_directions(path)
        if local_lines is None:
            return False
        head = path[-1]
        before_head = path[-2]
        head_horizontal = before_head[1] == head[1]
        head_line_key = ("h" if head_horizontal else "v", head[1] if head_horizontal else head[0])
        head_direction = (1 if head[0] > before_head[0] else -1) if head_horizontal else (1 if head[1] > before_head[1] else -1)
        previous_head_direction = head_line_directions.get(head_line_key)
        if previous_head_direction and previous_head_direction != head_direction:
            return False
        arrow = Arrow(
            id=len(arrows),
            path=list(path),
            dx=(head[0] > before_head[0]) - (head[0] < before_head[0]),
            dy=(head[1] > before_head[1]) - (head[1] < before_head[1]),
            color=rgb(COLORS[len(arrows) % len(COLORS)]),
        )
        occupied.update(path_keys)
        line_directions.update(local_lines)
        head_line_directions[head_line_key] = head_direction
        arrows.append(arrow)
        return True

    attempts = 0
    while len(arrows) < config["base_arrows"] and attempts < 100000:
        attempts += 1
        length = config["min_length"] + math.floor(rand() * config["length_span"])
        axis = "h" if rand() < .5 else "v"
        steps_to_turn = 1 + math.floor(rand() * 2)
        col, row = math.floor(rand() * cols), math.floor(rand() * rows)
        path: list[tuple[int, int]] = []
        for step in range(length):
            if not (0 <= col < cols and 0 <= row < rows):
                path.append((col, row))
                break
            path.append((col, row))
            direction = (horizontal_directions[row], 0) if axis == "h" else (0, vertical_directions[col])
            col += direction[0]
            row += direction[1]
            steps_to_turn -= 1
            if steps_to_turn <= 0 and step < length - 1:
                axis = "v" if axis == "h" else "h"
                steps_to_turn = 1 + math.floor(rand() * 2)
        if not all(0 <= c < cols and 0 <= r < rows for c, r in path):
            continue
        path_keys = set(path)
        if path_keys & occupied:
            continue
        head, before_head = path[-1], path[-2]
        dx = (head[0] > before_head[0]) - (head[0] < before_head[0])
        dy = (head[1] > before_head[1]) - (head[1] < before_head[1])
        clear_ray = True
        ray_col, ray_row = head[0] + dx, head[1] + dy
        while 0 <= ray_col < cols and 0 <= ray_row < rows:
            if (ray_col, ray_row) in occupied or (ray_col, ray_row) in path_keys:
                clear_ray = False
                break
            ray_col += dx
            ray_row += dy
        if clear_ray:
            add_arrow(path)

    def solve_removal_order(candidate: list[Arrow]) -> tuple[bool, list[Arrow], list[Arrow]]:
        remaining = list(candidate)
        occupied_now = {cell for arrow in remaining for cell in arrow.cells}
        order: list[Arrow] = []
        while remaining:
            next_index = next((index for index, arrow in enumerate(remaining) if arrow_can_leave_from_occupied(arrow, occupied_now, cols, rows)), -1)
            if next_index < 0:
                return False, order, remaining
            selected = remaining.pop(next_index)
            order.append(selected)
            for cell in selected.cells:
                occupied_now.discard(cell)
        return True, order, []

    extension_pass = 0
    while extension_pass < 30 and len(occupied) < config["extension_target"]:
        extension_pass += 1
        changed = False
        candidates = list(arrows)
        random.Random(int(rand() * 2**32)).shuffle(candidates)
        for arrow in candidates:
            first, next_cell = arrow.path[0], arrow.path[1]
            dx = (next_cell[0] > first[0]) - (next_cell[0] < first[0])
            dy = (next_cell[1] > first[1]) - (next_cell[1] < first[1])
            new_cell = (first[0] - dx, first[1] - dy)
            if not (0 <= new_cell[0] < cols and 0 <= new_cell[1] < rows) or new_cell in occupied:
                continue
            arrow.path.insert(0, new_cell)
            occupied.add(new_cell)
            solved, _, _ = solve_removal_order(arrows)
            if solved:
                changed = True
            else:
                arrow.path.pop(0)
                occupied.discard(new_cell)
        if not changed:
            break

    filler_paths: list[list[tuple[int, int]]] = []
    for row in range(rows):
        direction = horizontal_directions[row]
        for col in range(cols - 1):
            start_col = col if direction > 0 else col + 1
            filler_paths.append([(start_col, row), (start_col + direction, row)])
    for col in range(cols):
        direction = vertical_directions[col]
        for row in range(rows - 1):
            start_row = row if direction > 0 else row + 1
            filler_paths.append([(col, start_row), (col, start_row + direction)])
    random.Random(int(rand() * 2**32)).shuffle(filler_paths)
    for path in filler_paths:
        if len(occupied) >= config["filler_target"]:
            break
        path_keys = set(path)
        if path_keys & occupied:
            continue
        line_snapshot = dict(line_directions)
        head_snapshot = dict(head_line_directions)
        before_count = len(arrows)
        if not add_arrow(path):
            continue
        solved, _, _ = solve_removal_order(arrows)
        if solved:
            continue
        arrows.pop()
        occupied.difference_update(path_keys)
        line_directions = line_snapshot
        head_line_directions = head_snapshot
        # Keep IDs stable while generating and repair them again below.
        if len(arrows) != before_count:
            pass

    playable = arrows
    solved, _, remaining = solve_removal_order(playable)
    repair_attempts = 0
    while not solved and len(playable) > 12 and repair_attempts < 100:
        victim = remaining[-1]
        playable = [arrow for arrow in playable if arrow is not victim]
        solved, _, remaining = solve_removal_order(playable)
        repair_attempts += 1
    for index, arrow in enumerate(playable):
        arrow.id = index
    state = GameState(arrows=playable, level_number=level_number)
    state.profile = difficulty_profile(state)  # type: ignore[attr-defined]
    return state


def clone_level(template: GameState) -> GameState:
    arrows = []
    for arrow in template.arrows:
        arrows.append(Arrow(arrow.id, list(arrow.path), arrow.dx, arrow.dy, arrow.color))
    state = GameState(arrows=arrows, cols=template.cols, rows=template.rows, level_number=template.level_number)
    state.profile = copy.deepcopy(getattr(template, "profile", {}))  # type: ignore[attr-defined]
    return state


def format_duration(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def calculate_score(game: GameState) -> dict:
    elapsed = max(0, min(MAX_SECONDS, MAX_SECONDS - game.seconds_left))
    time_bonus = round(game.seconds_left / MAX_SECONDS * 70)
    life_bonus = round(game.lives / 3 * 30)
    return dict(elapsedSeconds=elapsed, timeBonus=time_bonus, lifeBonus=life_bonus, total=max(0, min(100, time_bonus + life_bonus)))


def consume_mistake(game: GameState) -> bool:
    """Consume one failed-click chance and return whether the game may continue."""
    game.lives = max(0, game.lives - 1)
    if game.lives == 0:
        game.dead = True
    return not game.dead


def font_path() -> str | None:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\Deng.ttf",
    ]
    return next((path for path in candidates if Path(path).exists()), None)


class ArrowPuzzle:
    def __init__(self, smoke_test: bool = False):
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.init()
        pygame.font.init()
        self.smoke_test = smoke_test
        display_info = pygame.display.Info()
        available_width = max(320, display_info.current_w - 80)
        available_height = max(480, display_info.current_h - 120)
        initial_scale = min(1.0, available_width / DESIGN_W, available_height / DESIGN_H)
        initial_size = (round(DESIGN_W * initial_scale), round(DESIGN_H * initial_scale))
        self.window = pygame.display.set_mode(initial_size, pygame.RESIZABLE)
        pygame.display.set_caption("一箭又一箭 · Python 复刻版")
        self.design = pygame.Surface((DESIGN_W, DESIGN_H), pygame.SRCALPHA)
        self.clock = pygame.time.Clock()
        self.running = True
        self.screen_name = "home"
        self.modal: str | None = None
        self.modal_copy = ""
        self.current_level = 1
        self.game: GameState | None = None
        self.level_cache: dict[int, GameState] = {}
        self.guides = False
        self.dark_mode = True
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.pan_dragging = False
        self.zoom_dragging = False
        self.pan_last = (0.0, 0.0)
        self.toast_text = ""
        self.toast_until = 0
        self.modal_next_text = "挑战下一关"
        self.history_path = Path(__file__).with_name("score_history.json")
        self.fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self.small_fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self.logo_surface = self.make_logo_surface()

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self.fonts:
            path = font_path()
            self.fonts[key] = pygame.font.Font(path, size) if path else pygame.font.SysFont("microsoftyahei", size, bold=bold)
            if bold:
                self.fonts[key].set_bold(True)
        return self.fonts[key]

    def text(self, surface: pygame.Surface, value: str, size: int, color, center: tuple[float, float], *, bold: bool = False, stroke: int = 0, stroke_color=(255, 255, 255), anchor="center"):
        font = self.font(size, bold)
        image = font.render(value, True, rgb(color))
        if stroke:
            outline = font.render(value, True, rgb(stroke_color))
            for dx in range(-stroke, stroke + 1):
                for dy in range(-stroke, stroke + 1):
                    if dx or dy:
                        pos = (center[0] - outline.get_width() / 2 + dx, center[1] - outline.get_height() / 2 + dy)
                        surface.blit(outline, pos)
        pos = (center[0] - image.get_width() / 2, center[1] - image.get_height() / 2)
        surface.blit(image, pos)

    def rounded_button(self, surface, rect, fill, label, *, text_color=(255, 255, 255), border=None, radius=14, size=20, bold=True, shadow=None):
        rect = pygame.Rect(rect)
        if shadow:
            pygame.draw.rect(surface, rgb(shadow), rect.move(0, 6), border_radius=radius)
        pygame.draw.rect(surface, rgb(fill), rect, border_radius=radius)
        if border:
            pygame.draw.rect(surface, rgb(border), rect, width=3, border_radius=radius)
        self.text(surface, label, size, text_color, rect.center, bold=bold)

    def make_logo_surface(self) -> pygame.Surface:
        surface = pygame.Surface((270, 205), pygame.SRCALPHA)
        arrow = [(5, 64), (145, 64), (145, 19), (260, 102), (145, 186), (145, 141), (5, 141)]
        pygame.draw.polygon(surface, rgb("#1d397e"), [(x, y + 6) for x, y in arrow])
        pygame.draw.polygon(surface, rgb("#329fe4"), arrow)
        pygame.draw.polygon(surface, rgb("#67daf2"), [(5, 64), (145, 64), (145, 19), (247, 95), (145, 95), (145, 112), (5, 112)])
        pygame.draw.polygon(surface, rgb("#1b67bf"), [(145, 112), (145, 186), (260, 102), (145, 19), (145, 64), (247, 95)])
        pygame.draw.line(surface, rgb("#eaffff"), (28, 77), (110, 77), 6)
        pygame.draw.line(surface, rgb("#bdf9fb"), (157, 55), (205, 102), 12)
        for x, y, w, h, pupil_x, pupil_y in [(63, 67, 44, 56, 16, 18), (115, 59, 42, 54, 15, 17)]:
            pygame.draw.ellipse(surface, rgb("#214783"), pygame.Rect(x - 3, y - 3, w + 6, h + 6))
            pygame.draw.ellipse(surface, rgb("#fffefa"), pygame.Rect(x, y, w, h))
            pygame.draw.ellipse(surface, rgb("#24233a"), pygame.Rect(x + pupil_x, y + pupil_y, 17, 24))
            pygame.draw.circle(surface, (255, 255, 255), (x + pupil_x + 5, y + pupil_y + 5), 4)
        pygame.draw.arc(surface, rgb("#173b78"), pygame.Rect(91, 116, 34, 18), 0, math.pi, 5)
        pygame.draw.rect(surface, rgb("#f47e8d"), pygame.Rect(100, 128, 15, 5), border_radius=3)
        return surface

    def draw_gear(self, surface: pygame.Surface, center: tuple[int, int], color, hole_color):
        cx, cy = center
        pygame.draw.circle(surface, rgb(color), center, 20)
        for index in range(8):
            angle = index * math.pi / 4
            tooth = pygame.Surface((12, 14), pygame.SRCALPHA)
            pygame.draw.rect(tooth, rgb(color), pygame.Rect(0, 0, 12, 14), border_radius=1)
            rotation = -math.degrees(angle + math.pi / 2)
            rotated_tooth = pygame.transform.rotate(tooth, rotation)
            tooth_center = (round(cx + math.cos(angle) * 23), round(cy + math.sin(angle) * 23))
            surface.blit(rotated_tooth, rotated_tooth.get_rect(center=tooth_center))
        pygame.draw.circle(surface, rgb(hole_color), (cx, cy), 10)
        pygame.draw.circle(surface, rgb(color), (cx, cy), 10, 3)

    def draw_heart(self, surface: pygame.Surface, center: tuple[int, int], color):
        cx, cy = center
        pygame.draw.circle(surface, rgb(color), (cx - 7, cy - 4), 8)
        pygame.draw.circle(surface, rgb(color), (cx + 7, cy - 4), 8)
        pygame.draw.polygon(surface, rgb(color), [(cx - 14, cy - 2), (cx + 14, cy - 2), (cx, cy + 15)])

    def draw_clock(self, surface: pygame.Surface, center: tuple[int, int], color):
        pygame.draw.circle(surface, rgb(color), center, 11, 3)
        pygame.draw.line(surface, rgb(color), center, (center[0], center[1] - 6), 2)
        pygame.draw.line(surface, rgb(color), center, (center[0] + 6, center[1] + 3), 2)

    def draw_guide(self, surface: pygame.Surface, center: tuple[int, int], color):
        cx, cy = center
        pygame.draw.circle(surface, rgb(color), center, 29, 4)
        for offset in (-10, 0, 10):
            pygame.draw.line(surface, rgb(color), (cx - 17, cy + offset), (cx + 17, cy + offset), 2)
            pygame.draw.line(surface, rgb(color), (cx + offset, cy - 17), (cx + offset, cy + 17), 2)

    def draw_toggle_icon(self, surface: pygame.Surface, center: tuple[int, int]):
        cx, cy = center
        if self.dark_mode:
            pygame.draw.circle(surface, rgb("#f9d739"), center, 21)
            pygame.draw.circle(surface, rgb("#5e87c5"), (cx + 8, cy - 7), 18)
        else:
            for index in range(8):
                angle = index * math.pi / 4
                pygame.draw.line(surface, rgb("#fffdf9"), (cx + math.cos(angle) * 13, cy + math.sin(angle) * 13), (cx + math.cos(angle) * 20, cy + math.sin(angle) * 20), 3)
            pygame.draw.circle(surface, rgb("#fffdf9"), center, 11)

    def level(self, number: int) -> GameState:
        if number not in self.level_cache:
            best = None
            best_score = -float("inf")
            for seed in LEVEL_CONFIGS[number]["seeds"]:
                candidate = build_level(seed, number)
                profile = getattr(candidate, "profile", {})
                variety = len({(arrow.dx, arrow.dy) for arrow in candidate.arrows})
                counts = profile.get("legal_counts", [])
                initial = counts[0] if counts else 99
                early = sum(counts[:12])
                score = (100000 if profile.get("solved") else 0) + len(candidate.arrows) * 1000 + profile.get("bottlenecks", 0) * 1800 + profile.get("unique_steps", 0) * 2600 + variety * 20000 - initial * 3500 - early * 120
                if best is None or score > best_score:
                    best, best_score = candidate, score
            self.level_cache[number] = best
        return clone_level(self.level_cache[number])

    def start_game(self):
        self.game = self.level(self.current_level)
        self.game.started_at = pygame.time.get_ticks()
        self.screen_name = "game"
        self.modal = None
        self.guides = False
        self.zoom = 1.0
        self.pan_x = self.pan_y = 0.0

    def set_toast(self, value: str, duration: int = 1300):
        self.toast_text = value
        self.toast_until = pygame.time.get_ticks() + duration

    def history(self) -> list[dict]:
        try:
            value = json.loads(self.history_path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def record_score(self, game: GameState):
        score = game.score or calculate_score(game)
        records = self.history()
        records.append({"level": game.level_number, "score": score["total"], "elapsedSeconds": score["elapsedSeconds"], "lives": game.lives, "timestamp": int(time.time() * 1000)})
        try:
            self.history_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def show_modal(self, mode: str, copy_text: str = ""):
        self.modal = mode
        self.modal_copy = copy_text

    def close_modal(self):
        self.modal = None

    def show_settings(self):
        self.show_modal("settings", f"当前是第 {self.current_level} 关，可以重新开始或返回主界面。")

    def show_level_selection(self):
        self.show_modal("level-selection", "选择想要挑战的关卡。")

    def show_history(self):
        self.show_modal("history", "每次通关都会记录在这里。")

    def show_failure(self):
        self.show_modal("failure", "三颗生命值都用完了，要再试一次吗？")

    def show_success(self):
        assert self.game
        self.modal_next_text = "挑战下一关" if self.game.level_number < 5 else "再挑战第1关"
        score = self.game.score or calculate_score(self.game)
        self.show_modal("success", f"第 {self.game.level_number} 关完成！\n用时 {format_duration(score['elapsedSeconds'])} · 剩余生命 {self.game.lives}\n通关得分：{score['total']} / 100 分")

    def lose_life(self):
        assert self.game
        consume_mistake(self.game)
        if self.game.dead:
            self.show_failure()

    def board_metrics(self):
        pad_x, pad_y = 24, 17
        cell = min((CANVAS_W - pad_x * 2) / self.game.cols, (CANVAS_H - pad_y * 2) / self.game.rows)  # type: ignore[union-attr]
        board_width, board_height = cell * self.game.cols, cell * self.game.rows  # type: ignore[union-attr]
        return pad_x + (CANVAS_W - pad_x * 2 - board_width) / 2, pad_y + (CANVAS_H - pad_y * 2 - board_height) / 2, cell, board_width, board_height

    def point_for(self, cell: tuple[float, float], metrics):
        pad_x, pad_y, size, _, _ = metrics
        return pad_x + (cell[0] + .5) * size, pad_y + (cell[1] + .5) * size

    def hit_test(self, x: float, y: float) -> Arrow | None:
        if not self.game:
            return None
        metrics = self.board_metrics()
        best, distance = None, float("inf")
        for arrow in self.game.arrows:
            if arrow.moving:
                continue
            points = [self.point_for(cell, metrics) for cell in arrow.path]
            for first, second in zip(points, points[1:]):
                dx, dy = second[0] - first[0], second[1] - first[1]
                length = math.hypot(dx, dy) or 1
                along = max(0, min(length, ((x - first[0]) * dx + (y - first[1]) * dy) / length))
                px, py = first[0] + dx / length * along, first[1] + dy / length * along
                current_distance = math.hypot(x - px, y - py)
                if current_distance < max(13, metrics[2] * .36) and current_distance < distance:
                    best, distance = arrow, current_distance
        return best

    def build_snake_route(self, arrow: Arrow):
        body_length = len(arrow.path) - 1
        head_col, head_row = arrow.path[-1]
        steps = arrow.dx and ((self.game.cols - head_col) if arrow.dx > 0 else (head_col + 1)) or ((self.game.rows - head_row) if arrow.dy > 0 else (head_row + 1))  # type: ignore[union-attr]
        move_distance = body_length + steps + 2
        route = [(float(col), float(row)) for col, row in arrow.path]
        for step in range(1, move_distance + 1):
            route.append((head_col + arrow.dx * step, head_row + arrow.dy * step))
        return route, move_distance

    def point_on_route(self, arrow: Arrow, distance: float, metrics):
        assert arrow.route
        safe = max(0, min(len(arrow.route) - 1, distance))
        lower = math.floor(safe)
        upper = min(len(arrow.route) - 1, lower + 1)
        amount = safe - lower
        first = self.point_for(arrow.route[lower], metrics)
        second = self.point_for(arrow.route[upper], metrics)
        return first[0] + (second[0] - first[0]) * amount, first[1] + (second[1] - first[1]) * amount

    def direction_on_route(self, arrow: Arrow, distance: float):
        assert arrow.route
        index = max(0, min(len(arrow.route) - 2, math.floor(distance)))
        current, next_cell = arrow.route[index], arrow.route[index + 1]
        return (int(math.copysign(1, next_cell[0] - current[0])) if next_cell[0] != current[0] else 0, int(math.copysign(1, next_cell[1] - current[1])) if next_cell[1] != current[1] else 0)

    def shoot(self, arrow: Arrow):
        # dead / complete 之后 update_game 不再推进动画，所以这里必须拒绝点击，
        # 否则箭头会卡在“飞行中”，棋盘永久无法再操作。
        if not self.game or arrow.moving or self.game.busy or self.game.complete or self.game.dead:
            return
        if not can_arrow_leave(self.game.arrows, arrow, self.game.cols, self.game.rows):
            info = get_block_info(self.game.arrows, arrow, self.game.cols, self.game.rows)
            self.lose_life()
            if self.game.lives > 0:
                message = "前方是自己的尾巴，不能走" if info["owner"] is arrow else "前方有箭身或尾巴挡住了"
                self.set_toast(f"{message} · 生命值 -1（剩余 {self.game.lives}）")
            return
        self.game.busy = True
        arrow.moving = True
        arrow.progress = 0
        arrow.route, arrow.move_distance = self.build_snake_route(arrow)
        arrow.move_started = pygame.time.get_ticks()
        arrow.duration = 340 + arrow.move_distance * 24

    def update_game(self, now: int):
        if not self.game or self.game.dead or self.game.complete:
            return
        self.game.seconds_left = max(0, MAX_SECONDS - (now - self.game.started_at) // 1000)
        if self.game.seconds_left == 0:
            self.game.dead = True
            self.show_modal("generic", "别着急，再来一局试试看。箭头迷宫每次都会重新排布。")
            return
        if self.game.busy:
            moving = next((arrow for arrow in self.game.arrows if arrow.moving), None)
            if moving:
                moving.progress = min(1.0, (now - moving.move_started) / moving.duration)
                if moving.progress >= 1:
                    self.game.arrows.remove(moving)
                    self.game.busy = False
                    if not self.game.arrows:
                        self.game.complete = True
                        self.game.score = calculate_score(self.game)
                        self.record_score(self.game)
                        self.show_success()

    def draw_board_surface(self) -> pygame.Surface:
        render_scale = BOARD_RENDER_SCALE
        surface = pygame.Surface((CANVAS_W * render_scale, CANVAS_H * render_scale), pygame.SRCALPHA)
        if not self.game:
            return surface
        base_metrics = self.board_metrics()
        metrics = tuple(value * render_scale for value in base_metrics)
        if self.guides:
            grid_color = rgba("#dae2fb", 28)
            for col in range(self.game.cols + 1):
                x = round(metrics[0] + col * metrics[2])
                pygame.draw.line(surface, grid_color, (x, metrics[1]), (x, metrics[1] + metrics[4]), render_scale)
            for row in range(self.game.rows + 1):
                y = round(metrics[1] + row * metrics[2])
                pygame.draw.line(surface, grid_color, (metrics[0], y), (metrics[0] + metrics[3], y), render_scale)
        for arrow in self.game.arrows:
            self.draw_arrow(surface, arrow, metrics)
        return surface

    def draw_arrow(self, surface: pygame.Surface, arrow: Arrow, metrics):
        body_length = len(arrow.path) - 1
        head_distance = body_length + arrow.move_distance * arrow.progress if arrow.moving else body_length
        direction = self.direction_on_route(arrow, head_distance) if arrow.moving else (arrow.dx, arrow.dy)
        direction_length = math.hypot(direction[0], direction[1]) or 1
        ux, uy = direction[0] / direction_length, direction[1] / direction_length
        points = [self.point_on_route(arrow, head_distance - (body_length - index), metrics) for index in range(len(arrow.path))] if arrow.moving else [self.point_for(cell, metrics) for cell in arrow.path]
        color = arrow.color
        width = max(4, round(metrics[2] * .21))
        if len(points) > 1:
            pixel_points = [(round(x), round(y)) for x, y in points]
            shadow_points = [(x, y + round(width * .32)) for x, y in pixel_points]
            pygame.draw.lines(surface, (*color, 70), False, shadow_points, width + round(width * .9))
            pygame.draw.aalines(surface, color, False, pixel_points, 1)
            pygame.draw.lines(surface, color, False, pixel_points, width)
            radius = width // 2
            pygame.draw.circle(surface, color, pixel_points[0], radius)
            pygame.draw.circle(surface, color, pixel_points[-1], radius)
            for index in range(1, len(pixel_points) - 1):
                before = pixel_points[index - 1]
                current = pixel_points[index]
                after = pixel_points[index + 1]
                before_direction = (current[0] - before[0], current[1] - before[1])
                after_direction = (after[0] - current[0], after[1] - current[1])
                if before_direction != after_direction:
                    pygame.draw.circle(surface, color, current, radius)
        tip = points[-1]
        tip_x, tip_y = tip[0] + ux * metrics[2] * .35, tip[1] + uy * metrics[2] * .35
        wing = metrics[2] * .35
        triangle = [(tip_x, tip_y), (tip_x - ux * wing - uy * wing * .75, tip_y - uy * wing + ux * wing * .75), (tip_x - ux * wing + uy * wing * .75, tip_y - uy * wing - ux * wing * .75)]
        pygame.draw.polygon(surface, color, [(round(x), round(y)) for x, y in triangle])
        if arrow.hint and not arrow.moving and pygame.time.get_ticks() < arrow.hint_until:
            pygame.draw.circle(surface, rgb("#fff5a8"), (round(tip[0]), round(tip[1])), round(metrics[2] * .58), 2)

    def base_canvas_rect(self):
        return pygame.Rect(16, 192, 560, round(560 * 560 / 420))

    def pan_limits(self):
        rect = self.base_canvas_rect()
        distance = abs(self.zoom - 1)
        return rect.width * distance * .5 + 40, rect.height * distance * .5 + 80

    def apply_pan(self):
        limit_x, limit_y = self.pan_limits()
        self.pan_x = max(-limit_x, min(limit_x, self.pan_x))
        self.pan_y = max(-limit_y, min(limit_y, self.pan_y))

    def board_screen_rect(self):
        base = self.base_canvas_rect()
        width, height = base.width * self.zoom, base.height * self.zoom
        left = base.centerx + self.pan_x - width / 2
        top = base.centery + self.pan_y - height / 2
        return pygame.Rect(round(left), round(top), round(width), round(height))

    def board_point(self, position: tuple[float, float]):
        rect = self.board_screen_rect()
        if rect.width == 0 or rect.height == 0:
            return 0, 0
        return (position[0] - rect.left) / rect.width * CANVAS_W, (position[1] - rect.top) / rect.height * CANVAS_H

    def zoom_from_x(self, x: float):
        left, width = 135, 322
        ratio = max(0.0, min(1.0, (x - left) / width))
        self.zoom = MIN_ZOOM + ratio * (MAX_ZOOM - MIN_ZOOM)
        self.apply_pan()

    def draw_background(self, now: int = 0):
        if self.screen_name == "home":
            self.design.fill(rgb("#d9f6f7"))
            pattern = pygame.Surface((DESIGN_W, DESIGN_H), pygame.SRCALPHA)
            travel = (now * .04) % 150
            outline = (105, 121, 130, 72)
            for x in range(-70, DESIGN_W + 100, 110):
                for base_y in range(-150, DESIGN_H + 150, 150):
                    y = base_y - travel
                    points = [(x + 45, y), (x + 72, y + 38), (x + 58, y + 38), (x + 58, y + 84), (x + 32, y + 84), (x + 32, y + 38), (x + 18, y + 38)]
                    pygame.draw.lines(pattern, outline, True, points, 2)
            self.design.blit(pattern, (0, 0))
        else:
            self.design.fill(rgb("#e7f4f1" if not self.dark_mode else "#3b405f"))

    def draw_home(self, now: int):
        self.draw_background(now)
        self.text(self.design, "ARROW  ·  PUZZLE", 13, "#4c91c5", (DESIGN_W / 2, 112), bold=True)
        title_y = 160
        self.text(self.design, "一", 62, "#358fd5", (159, title_y), bold=True, stroke=4)
        self.text(self.design, "箭", 62, "#f2bc2f", (223, title_y), bold=True, stroke=4)
        self.text(self.design, "↗", 31, "#f28272", (283, title_y), bold=True, stroke=3)
        self.text(self.design, "又", 68, "#ef856e", (344, title_y), bold=True, stroke=4)
        self.text(self.design, "一箭", 54, "#35bd91", (430, title_y), bold=True, stroke=4)
        self.text(self.design, "每一步，都要找到出口", 16, "#687b87", (DESIGN_W / 2, 215), bold=True)
        angle = (now / 48) % 360
        logo = pygame.transform.rotozoom(self.logo_surface, -angle, .98)
        self.design.blit(logo, (DESIGN_W / 2 - logo.get_width() / 2, 400 - logo.get_height() / 2))
        self.text(self.design, f"第 {self.current_level} 关", 29, "#564937", (DESIGN_W / 2, 795), bold=True)
        start_rect = pygame.Rect(141, 820, 310, 78)
        self.rounded_button(self.design, start_rect, "#328ee2", "开始游戏", border="#2572c3", shadow="#2362a6", size=29)
        pygame.draw.polygon(self.design, (255, 255, 255), [(208, 846), (208, 874), (232, 860)])
        self.rounded_button(self.design, pygame.Rect(125, 925, 160, 42), "#ffffff", "选择关卡", text_color="#397c9d", border="#79b8cb", radius=21, size=16)
        self.rounded_button(self.design, pygame.Rect(307, 925, 160, 42), "#ffffff", "历史得分", text_color="#397c9d", border="#79b8cb", radius=21, size=16)

    def draw_toggle(self):
        rect = pygame.Rect(106, 49, 100, 55)
        pygame.draw.rect(self.design, rgb("#5e87c5" if self.dark_mode else "#f2c84b"), rect, border_radius=28)
        self.draw_toggle_icon(self.design, (rect.right - 28 if self.dark_mode else rect.left + 28, rect.centery))

    def draw_game(self, now: int):
        self.draw_background(now)
        pygame.draw.line(self.design, rgba("#d2dcf5", 130) if self.dark_mode else rgba("#4c818b", 72), (0, 126), (DESIGN_W, 126), 2)
        setting_rect = pygame.Rect(22, 42, 68, 68)
        setting_bg = "#3e4a6b" if self.dark_mode else "#fffdf9"
        setting_color = "#ffffff" if self.dark_mode else "#45616b"
        self.rounded_button(self.design, setting_rect, setting_bg, "", border="#4cdbc1" if self.dark_mode else "#73c8bf", radius=20, size=34)
        self.draw_gear(self.design, setting_rect.center, setting_color, setting_bg)
        self.draw_toggle()
        assert self.game
        time_color = "#ffffff" if self.dark_mode else "#344858"
        self.text(self.design, f"关卡{self.game.level_number}", 27, "#ffffff" if self.dark_mode else "#344858", (DESIGN_W / 2, 44), bold=True)
        restart_rect = pygame.Rect(211, 48, 68, 42)
        self.rounded_button(self.design, restart_rect, "#3e4a6b" if self.dark_mode else "#fffdf9", "重玩", text_color="#ffffff" if self.dark_mode else "#3c5965", border="#4cdbc1" if self.dark_mode else "#73c8bf", radius=16, size=14)
        self.text(self.design, f"剩余 {len(self.game.arrows)}", 14, time_color, (214, 93), bold=True)
        for index in range(3):
            self.draw_heart(self.design, (round(DESIGN_W / 2 - 25 + index * 25), 92), "#fa5b5f" if index < self.game.lives else "#67708a")
        self.draw_clock(self.design, (408, 76), time_color)
        self.text(self.design, format_duration(self.game.seconds_left), 22, time_color, (453, 76), bold=True)
        menu = pygame.Rect(492, 48, 78, 54)
        pygame.draw.rect(self.design, rgb("#2e3654" if self.dark_mode else "#8dbcc0"), menu, border_radius=28)
        self.text(self.design, "•••", 27, "#ffffff", menu.center, bold=True)
        board = self.draw_board_surface()
        rect = self.board_screen_rect()
        scaled = pygame.transform.smoothscale(board, (rect.width, rect.height))
        self.design.blit(scaled, rect)
        toolbar_y = DESIGN_H - 97
        pygame.draw.line(self.design, rgba("#dce4f9", 140) if self.dark_mode else rgba("#4c818b", 75), (0, toolbar_y), (DESIGN_W, toolbar_y), 1)
        self.text(self.design, "●", 42, "#f5bd30", (56, toolbar_y + 32), bold=True)
        self.text(self.design, "提示", 16, "#ffffff" if self.dark_mode else "#3c5965", (56, toolbar_y + 74), bold=True)
        self.draw_guide(self.design, (536, toolbar_y + 32), "#1ecdb4")
        self.text(self.design, "辅助线", 16, "#ffffff" if self.dark_mode else "#3c5965", (536, toolbar_y + 74), bold=True)
        pygame.draw.rect(self.design, rgb("#71798c" if self.dark_mode else "#b7d5d7"), pygame.Rect(130, toolbar_y + 25, 332, 32), border_radius=17)
        pygame.draw.line(self.design, rgb("#aab1c4" if self.dark_mode else "#e5f1ef"), (135, toolbar_y + 41), (457, toolbar_y + 41), 8)
        percent = (self.zoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM)
        fill_x = 135 + round(percent * 322)
        pygame.draw.line(self.design, rgb("#5dbbc4"), (135, toolbar_y + 41), (fill_x, toolbar_y + 41), 8)
        pygame.draw.circle(self.design, rgb("#eaf5ee"), (fill_x, toolbar_y + 41), 11)
        pygame.draw.circle(self.design, rgb("#46c5bb"), (fill_x, toolbar_y + 41), 11, 3)
        self.text(self.design, "−", 34, "#ffffff" if self.dark_mode else "#3c5965", (113, toolbar_y + 40), bold=True)
        self.text(self.design, "＋", 30, "#ffffff" if self.dark_mode else "#3c5965", (480, toolbar_y + 40), bold=True)
        if self.toast_text and pygame.time.get_ticks() < self.toast_until:
            toast_rect = pygame.Rect(130, 155, 332, 40)
            pygame.draw.rect(self.design, rgba("#151a34", 225), toast_rect, border_radius=20)
            self.text(self.design, self.toast_text, 14, "#ffffff", toast_rect.center)

    def draw_modal(self):
        overlay = pygame.Surface((DESIGN_W, DESIGN_H), pygame.SRCALPHA)
        overlay.fill((23, 32, 62, 125))
        self.design.blit(overlay, (0, 0))
        card = pygame.Rect(111, 300, 370, 430 if self.modal == "history" else 370)
        pygame.draw.rect(self.design, rgb("#fffdf9"), card, border_radius=28)
        pygame.draw.rect(self.design, rgba("#112957", 55), card.move(0, 10), width=5, border_radius=28)
        self.rounded_button(self.design, pygame.Rect(card.right - 55, card.top + 10, 40, 40), "#fffdf9", "×", text_color="#778096", radius=18, size=28, bold=False)
        self.rounded_button(self.design, pygame.Rect(card.centerx - 72, card.top + 28, 144, 30), "#dcf4f3", "一箭又一箭", text_color="#2c9c9e", radius=15, size=14)
        titles = {"settings": "设置", "level-selection": "选择关卡", "failure": "挑战失败", "success": "通关成功！", "history": "历史得分", "menu": "关卡菜单", "generic": "时间到啦"}
        self.text(self.design, titles.get(self.modal, "提示"), 27, "#3d4050", (card.centerx, card.top + 102), bold=True)
        if self.modal == "history":
            self.text(self.design, self.modal_copy, 15, "#667083", (card.centerx, card.top + 135))
            records = list(reversed(self.history()))
            if not records:
                self.text(self.design, "还没有通关记录，先完成一关吧！", 15, "#7c8797", (card.centerx, card.top + 215))
            else:
                y = card.top + 165
                for record in records[-7:]:
                    entry = pygame.Rect(card.left + 18, y, card.width - 36, 57)
                    pygame.draw.rect(self.design, rgb("#f0f6f7"), entry, border_radius=13)
                    self.text(self.design, f"第 {record.get('level', '?')} 关 · 用时 {format_duration(int(record.get('elapsedSeconds', 0)))}", 14, "#2e9699", (entry.left + 90, entry.top + 17), bold=True)
                    self.text(self.design, f"{record.get('score', 0)} 分", 19, "#e39d20", (entry.right - 52, entry.top + 17), bold=True)
                    stamp = datetime.fromtimestamp(record.get("timestamp", 0) / 1000).strftime("%m月%d日 %H:%M")
                    self.text(self.design, f"剩余生命 {record.get('lives', 0)} · {stamp}", 11, "#8993a2", (entry.centerx, entry.bottom - 13))
                    y += 64
            self.rounded_button(self.design, pygame.Rect(card.centerx - 54, card.bottom - 56, 108, 40), "#338fdf", "知道了", size=16, radius=12)
            return
        lines = self.modal_copy.split("\n")
        if self.modal == "success":
            copy_y = card.top + 145
            for line in lines:
                self.text(self.design, line, 15, "#667083", (card.centerx, copy_y))
                copy_y += 28
            self.rounded_button(self.design, pygame.Rect(card.left + 24, card.bottom - 105, 100, 44), "#eef1f7", "回到主界面", text_color="#536078", radius=12, size=13)
            self.rounded_button(self.design, pygame.Rect(card.centerx - 50, card.bottom - 105, 100, 44), "#eef1f7", self.modal_next_text, text_color="#536078", radius=12, size=13)
            self.rounded_button(self.design, pygame.Rect(card.right - 124, card.bottom - 105, 100, 44), "#eef1f7", "选择关卡", text_color="#536078", radius=12, size=13)
            return
        if self.modal in ("settings", "level-selection"):
            self.text(self.design, self.modal_copy, 15, "#667083", (card.centerx, card.top + 145))
            self.text(self.design, "选择关卡" if self.modal == "settings" else "开始挑战", 15, "#687286", (card.centerx, card.top + 184), bold=True)
            for index in range(1, 6):
                rect = pygame.Rect(card.left + 52 + (index - 1) * 54, card.top + 204, 42, 42)
                self.rounded_button(self.design, rect, "#4ac4b6" if index == self.current_level else "#dff3f1", str(index), text_color="#ffffff" if index == self.current_level else "#2e9699", radius=13, size=20)
            if self.modal == "settings":
                self.rounded_button(self.design, pygame.Rect(card.left + 30, card.bottom - 66, 145, 42), "#eef1f7", "重玩当前关卡", text_color="#536078", radius=12, size=14)
                self.rounded_button(self.design, pygame.Rect(card.right - 175, card.bottom - 66, 145, 42), "#eef1f7", "回到主界面", text_color="#536078", radius=12, size=14)
            return
        self.text(self.design, self.modal_copy, 15, "#667083", (card.centerx, card.top + 150))
        if self.modal == "failure":
            self.rounded_button(self.design, pygame.Rect(card.left + 30, card.bottom - 70, 145, 44), "#eef1f7", "重玩当前关卡", text_color="#536078", radius=12, size=14)
            self.rounded_button(self.design, pygame.Rect(card.right - 175, card.bottom - 70, 145, 44), "#eef1f7", "回到主界面", text_color="#536078", radius=12, size=14)
        else:
            self.rounded_button(self.design, pygame.Rect(card.centerx - 54, card.bottom - 62, 108, 42), "#338fdf", "知道了", radius=12, size=16)

    def design_position(self, position: tuple[int, int]) -> tuple[float, float]:
        window_w, window_h = self.window.get_size()
        scale = min(window_w / DESIGN_W, window_h / DESIGN_H)
        offset_x = (window_w - DESIGN_W * scale) / 2
        offset_y = (window_h - DESIGN_H * scale) / 2
        return (position[0] - offset_x) / scale, (position[1] - offset_y) / scale

    def rect_contains(self, rect, point):
        return pygame.Rect(rect).collidepoint(point)

    def choose_level_at(self, position) -> bool:
        if self.modal not in ("settings", "level-selection"):
            return False
        card = pygame.Rect(111, 300, 370, 370)
        for index in range(1, 6):
            rect = pygame.Rect(card.left + 52 + (index - 1) * 54, card.top + 204, 42, 42)
            if rect.collidepoint(position):
                self.current_level = index
                self.start_game()
                return True
        return False

    def handle_modal_click(self, position):
        if self.modal is None:
            return
        card = pygame.Rect(111, 300, 370, 430 if self.modal == "history" else 370)
        if pygame.Rect(card.right - 55, card.top + 10, 40, 40).collidepoint(position):
            self.close_modal()
            return
        if self.modal == "history":
            if pygame.Rect(card.centerx - 54, card.bottom - 56, 108, 40).collidepoint(position):
                self.close_modal()
            return
        if self.choose_level_at(position):
            return
        if self.modal == "settings":
            if pygame.Rect(card.left + 30, card.bottom - 66, 145, 42).collidepoint(position):
                self.start_game()
            elif pygame.Rect(card.right - 175, card.bottom - 66, 145, 42).collidepoint(position):
                self.go_home()
            return
        if self.modal == "failure":
            if pygame.Rect(card.left + 30, card.bottom - 70, 145, 44).collidepoint(position):
                self.start_game()
            elif pygame.Rect(card.right - 175, card.bottom - 70, 145, 44).collidepoint(position):
                self.go_home()
            return
        if self.modal == "success":
            if pygame.Rect(card.left + 24, card.bottom - 105, 100, 44).collidepoint(position):
                self.go_home()
            elif pygame.Rect(card.centerx - 50, card.bottom - 105, 100, 44).collidepoint(position):
                self.current_level = 1 if self.current_level >= 5 else self.current_level + 1
                self.start_game()
            elif pygame.Rect(card.right - 124, card.bottom - 105, 100, 44).collidepoint(position):
                self.show_settings()
            return
        if pygame.Rect(card.centerx - 54, card.bottom - 62, 108, 42).collidepoint(position):
            self.close_modal()

    def go_home(self):
        self.modal = None
        self.game = None
        self.screen_name = "home"
        self.pan_x = self.pan_y = 0

    def handle_mouse_down(self, position):
        if self.modal:
            self.handle_modal_click(position)
            return
        if self.screen_name == "home":
            if self.rect_contains((141, 820, 310, 78), position):
                self.start_game()
            elif self.rect_contains((125, 925, 160, 42), position):
                self.show_level_selection()
            elif self.rect_contains((307, 925, 160, 42), position):
                self.show_history()
            return
        if not self.game:
            return
        if self.rect_contains((22, 42, 68, 68), position):
            self.show_settings()
            return
        if self.rect_contains((106, 49, 100, 55), position):
            self.dark_mode = not self.dark_mode
            self.set_toast("夜间模式" if self.dark_mode else "明亮模式")
            return
        if self.rect_contains((211, 48, 68, 42), position):
            self.start_game()
            return
        if self.rect_contains((492, 48, 78, 54), position):
            self.show_modal("menu", f"当前还剩 {len(self.game.arrows)} 支箭头。")
            return
        toolbar_y = DESIGN_H - 97
        if position[1] >= toolbar_y:
            if self.rect_contains((20, toolbar_y + 5, 75, 83), position):
                available = next((arrow for arrow in self.game.arrows if can_arrow_leave(self.game.arrows, arrow, self.game.cols, self.game.rows)), None)
                if available:
                    available.hint = True
                    available.hint_until = pygame.time.get_ticks() + 1600
                    self.set_toast("试试这支箭", 1600)
                else:
                    self.set_toast("再等等，先清出一条路")
                return
            if self.rect_contains((497, toolbar_y + 5, 75, 83), position):
                self.guides = not self.guides
                self.set_toast("辅助线已开启" if self.guides else "辅助线已关闭")
                return
            if self.rect_contains((125, toolbar_y + 8, 342, 58), position):
                self.zoom_dragging = True
                self.zoom_from_x(position[0])
                return
            if self.rect_contains((92, toolbar_y + 8, 40, 60), position):
                self.zoom = max(MIN_ZOOM, self.zoom - .08)
                self.apply_pan()
                return
            if self.rect_contains((467, toolbar_y + 8, 40, 60), position):
                self.zoom = min(MAX_ZOOM, self.zoom + .08)
                self.apply_pan()
                return
        board_rect = self.board_screen_rect()
        if board_rect.collidepoint(position):
            x, y = self.board_point(position)
            arrow = self.hit_test(x, y)
            if arrow:
                self.shoot(arrow)
            else:
                self.pan_dragging = True
                self.pan_last = position

    def handle_mouse_motion(self, position):
        if self.zoom_dragging:
            self.zoom_from_x(position[0])
        elif self.pan_dragging:
            self.pan_x += position[0] - self.pan_last[0]
            self.pan_y += position[1] - self.pan_last[1]
            self.pan_last = position
            self.apply_pan()

    def process_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.VIDEORESIZE:
                self.window = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_mouse_down(self.design_position(event.pos))
            elif event.type == pygame.MOUSEMOTION:
                self.handle_mouse_motion(self.design_position(event.pos))
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.pan_dragging = False
                self.zoom_dragging = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.close_modal()

    def draw(self):
        now = pygame.time.get_ticks()
        if self.screen_name == "home":
            self.draw_home(now)
        else:
            self.draw_game(now)
        if self.modal:
            self.draw_modal()
        window_w, window_h = self.window.get_size()
        scale = min(window_w / DESIGN_W, window_h / DESIGN_H)
        scaled = pygame.transform.smoothscale(self.design, (round(DESIGN_W * scale), round(DESIGN_H * scale)))
        self.window.fill((20, 25, 45))
        self.window.blit(scaled, ((window_w - scaled.get_width()) // 2, (window_h - scaled.get_height()) // 2))
        pygame.display.flip()

    def run(self):
        if self.smoke_test:
            for number in range(1, 6):
                self.level(number)
            return 0
        while self.running:
            self.process_events()
            self.update_game(pygame.time.get_ticks())
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="一箭又一箭 Python / Pygame 复刻版")
    parser.add_argument("--smoke-test", action="store_true", help="生成全部关卡并退出，用于检查安装和算法")
    args = parser.parse_args()
    app = ArrowPuzzle(smoke_test=args.smoke_test)
    try:
        return app.run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
