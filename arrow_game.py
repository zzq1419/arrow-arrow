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

def main() -> int:
    """规则层自检：生成全部关卡并检查可解性。"""
    parser = argparse.ArgumentParser(description="一箭又一箭 · 规则层与关卡生成器")
    parser.add_argument("--smoke-test", action="store_true", help="生成全部关卡并检查是否可解")
    parser.parse_args()
    for number in sorted(LEVEL_CONFIGS):
        level = build_level(LEVEL_CONFIGS[number]["seeds"][0], number)
        profile = difficulty_profile(level)
        print(f"第 {number} 关：{len(level.arrows)} 支箭头，可解={profile['solved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
