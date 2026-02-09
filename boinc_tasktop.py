#!/usr/bin/env python3

from __future__ import annotations

import argparse
import curses
import re
import shlex
import socket
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlparse

TASK_HEADER_RE = re.compile(r"^\s*(\d+)\)\s*-+")
KV_RE = re.compile(r"^\s*([^:]+):\s*(.*)$")
CPU_RES_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*CPUs?$", re.IGNORECASE)
GPU_RES_RE = re.compile(r"^([0-9]*\.?[0-9]+)\s*(.+?)\s*GPUs?$", re.IGNORECASE)


@dataclass
class Task:
    index: int
    name: str = ""
    wu_name: str = ""
    project_url: str = ""
    state: str = ""
    scheduler_state: str = ""
    active_task_state: str = ""
    resources: str = ""
    fraction_done: float | None = None
    elapsed_task_time: float | None = None
    estimated_cpu_time_remaining: float | None = None
    pid: int | None = None
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.active_task_state.upper() == "EXECUTING"

    @property
    def project(self) -> str:
        if not self.project_url:
            return "-"
        parsed = urlparse(self.project_url)
        return parsed.netloc or self.project_url

    @property
    def display_state(self) -> str:
        if self.active_task_state:
            return self.active_task_state
        if self.scheduler_state:
            return self.scheduler_state
        return self.state or "-"

    def parse_resources(self) -> Tuple[float, Dict[str, float], float]:
        cpu = 0.0
        gpu_by_type: Dict[str, float] = {}
        if not self.resources:
            return cpu, gpu_by_type, 0.0

        for part in [p.strip() for p in self.resources.split("+") if p.strip()]:
            cpu_match = CPU_RES_RE.match(part)
            if cpu_match:
                cpu += float(cpu_match.group(1))
                continue

            gpu_match = GPU_RES_RE.match(part)
            if gpu_match:
                count = float(gpu_match.group(1))
                gpu_type = re.sub(r"\s+", " ", gpu_match.group(2).strip())
                gpu_by_type[gpu_type] = gpu_by_type.get(gpu_type, 0.0) + count

        gpu_total = sum(gpu_by_type.values())
        return cpu, gpu_by_type, gpu_total


def normalize_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_")


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def task_from_dict(data: dict[str, str]) -> Task:
    return Task(
        index=int(data.get("index", "0")),
        name=data.get("name", ""),
        wu_name=data.get("wu_name", ""),
        project_url=data.get("project_url", ""),
        state=data.get("state", ""),
        scheduler_state=data.get("scheduler_state", ""),
        active_task_state=data.get("active_task_state", ""),
        resources=data.get("resources", ""),
        fraction_done=parse_float(data.get("fraction_done")),
        elapsed_task_time=parse_float(data.get("elapsed_task_time")),
        estimated_cpu_time_remaining=parse_float(data.get("estimated_cpu_time_remaining")),
        pid=parse_int(data.get("pid")),
        raw=data,
    )


def parse_tasks(output: str) -> List[Task]:
    tasks: List[Task] = []
    in_tasks_section = False
    current: dict[str, str] | None = None

    for line in output.splitlines():
        if line.startswith("========"):
            in_tasks_section = "Tasks" in line
            continue

        if not in_tasks_section:
            continue

        header = TASK_HEADER_RE.match(line)
        if header:
            if current is not None:
                tasks.append(task_from_dict(current))
            current = {"index": header.group(1)}
            continue

        if current is None:
            continue

        key_val = KV_RE.match(line)
        if not key_val:
            continue

        key = normalize_key(key_val.group(1))
        value = key_val.group(2).strip()
        current[key] = value

    if current is not None:
        tasks.append(task_from_dict(current))

    return tasks


def run_get_tasks_command(base_cmd: Sequence[str], use_sudo_fallback: bool = True) -> str:
    commands: List[List[str]] = [list(base_cmd) + ["--get_tasks"]]
    fallback = ["sudo", "-n", "-u", "boinc"] + list(base_cmd) + ["--get_tasks"]
    if use_sudo_fallback and commands[0] != fallback:
        commands.append(fallback)

    last_error = ""
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{' '.join(cmd)} failed: {exc}"
            continue

        if result.returncode == 0:
            return result.stdout

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr if stderr else stdout
        last_error = f"{' '.join(cmd)} failed: {detail or 'unknown error'}"

    raise RuntimeError(last_error or "Unable to execute boinccmd --get_tasks")


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 99:
        return f"{hours}h"
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"


def format_percent(fraction: float | None) -> str:
    if fraction is None:
        return "-"
    return f"{fraction * 100.0:5.1f}%"


def short_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def format_gpu_summary(gpu_map: Dict[str, float]) -> str:
    if not gpu_map:
        return "0"
    parts = [f"{count:g} {gpu_type}" for gpu_type, count in sorted(gpu_map.items())]
    return ", ".join(parts)


def aggregate_running_resources(tasks: Sequence[Task]) -> Tuple[float, Dict[str, float]]:
    cpu_total = 0.0
    gpu_total: Dict[str, float] = {}
    for task in tasks:
        if not task.is_running:
            continue
        cpu, gpu_map, _ = task.parse_resources()
        cpu_total += cpu
        for gpu_type, count in gpu_map.items():
            gpu_total[gpu_type] = gpu_total.get(gpu_type, 0.0) + count
    return cpu_total, gpu_total


def build_table_rows(tasks: Sequence[Task], show_all: bool) -> List[Tuple[Task, float, float]]:
    selected = list(tasks) if show_all else [t for t in tasks if t.is_running]
    selected.sort(key=lambda t: (not t.is_running, t.project, t.name, t.index))
    rows: List[Tuple[Task, float, float]] = []
    for task in selected:
        cpu, _, gpu_total = task.parse_resources()
        rows.append((task, cpu, gpu_total))
    return rows


def draw_ui(
    stdscr: "curses._CursesWindow",
    tasks: Sequence[Task],
    show_all: bool,
    interval: float,
    scroll: int,
    last_error: str | None,
    last_success_ts: float | None,
) -> None:
    height, width = stdscr.getmaxyx()
    stdscr.erase()

    host = socket.gethostname()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    running_count = sum(1 for t in tasks if t.is_running)
    cpu_total, gpu_total = aggregate_running_resources(tasks)
    gpu_summary = format_gpu_summary(gpu_total)

    states = Counter(t.display_state.upper() or "-" for t in tasks)
    states_line = ", ".join(f"{state}:{count}" for state, count in states.most_common(5))

    header = f"boinc-tasktop  host={host}  now={now_str}"
    mode = "all tasks" if show_all else "running only"
    summary = (
        f"tasks: running {running_count}/{len(tasks)}  mode={mode}  "
        f"res(running): CPU {cpu_total:g}, GPU {gpu_summary}"
    )
    control = f"keys: q quit | a toggle mode | r refresh | +/- interval ({interval:.1f}s) | arrows scroll"

    stdscr.addnstr(0, 0, header, width - 1)
    stdscr.addnstr(1, 0, summary, width - 1)
    stdscr.addnstr(2, 0, f"states: {states_line or '-'}", width - 1)
    stdscr.addnstr(3, 0, control, width - 1)

    if last_error:
        stdscr.addnstr(4, 0, f"last error: {last_error}", width - 1, curses.A_BOLD)
    elif last_success_ts:
        age = max(0, int(time.time() - last_success_ts))
        stdscr.addnstr(4, 0, f"last update: {age}s ago", width - 1)

    table_top = 6
    if height <= table_top + 1:
        stdscr.addnstr(height - 1, 0, "Terminal window too small.", width - 1)
        stdscr.refresh()
        return

    rows = build_table_rows(tasks, show_all)
    visible_rows = max(1, height - table_top - 1)
    max_scroll = max(0, len(rows) - visible_rows)
    scroll = max(0, min(scroll, max_scroll))

    columns = [
        ("#", 4),
        ("Project", 22),
        ("Task", 34),
        ("State", 14),
        ("CPU", 6),
        ("GPU", 6),
        ("Done", 7),
        ("ETA", 8),
    ]

    x = 0
    for title, col_width in columns:
        stdscr.addnstr(table_top - 1, x, title.ljust(col_width), col_width, curses.A_UNDERLINE)
        x += col_width + 1
        if x >= width - 1:
            break

    for row_num, (task, cpu, gpu) in enumerate(rows[scroll : scroll + visible_rows], start=table_top):
        row_fields = [
            str(task.index),
            task.project,
            task.name or task.wu_name or "-",
            task.display_state,
            f"{cpu:g}" if cpu else "0",
            f"{gpu:g}" if gpu else "0",
            format_percent(task.fraction_done),
            format_seconds(task.estimated_cpu_time_remaining),
        ]

        x = 0
        attr = curses.A_BOLD if task.is_running else curses.A_NORMAL
        for (value, (_, col_width)) in zip(row_fields, columns):
            stdscr.addnstr(row_num, x, short_text(value, col_width).ljust(col_width), col_width, attr)
            x += col_width + 1
            if x >= width - 1:
                break

    stdscr.refresh()


def print_once(tasks: Sequence[Task], show_all: bool) -> None:
    rows = build_table_rows(tasks, show_all)
    running_count = sum(1 for t in tasks if t.is_running)
    cpu_total, gpu_total = aggregate_running_resources(tasks)

    print(
        f"tasks running {running_count}/{len(tasks)} | "
        f"resources (running): CPU {cpu_total:g}, GPU {format_gpu_summary(gpu_total)}"
    )
    print("IDX  PROJECT                  STATE         CPU  GPU  DONE   ETA     TASK")
    for task, cpu, gpu in rows:
        print(
            f"{task.index:>3}  "
            f"{short_text(task.project, 22):<22}  "
            f"{short_text(task.display_state, 12):<12}  "
            f"{cpu:>4g}  {gpu:>4g}  "
            f"{format_percent(task.fraction_done):>6}  "
            f"{format_seconds(task.estimated_cpu_time_remaining):>7}  "
            f"{task.name or task.wu_name or '-'}"
        )


def run_tui(tasks_cmd: Sequence[str], show_all_initial: bool, interval: float, no_sudo_fallback: bool) -> int:
    def _inner(stdscr: "curses._CursesWindow") -> int:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)

        show_all = show_all_initial
        refresh_interval = interval
        scroll = 0
        next_refresh = 0.0
        tasks: List[Task] = []
        last_error: str | None = None
        last_success_ts: float | None = None

        while True:
            now = time.monotonic()
            if now >= next_refresh:
                try:
                    output = run_get_tasks_command(tasks_cmd, use_sudo_fallback=not no_sudo_fallback)
                    tasks = parse_tasks(output)
                    last_error = None
                    last_success_ts = time.time()
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                next_refresh = now + refresh_interval

            draw_ui(stdscr, tasks, show_all, refresh_interval, scroll, last_error, last_success_ts)

            key = stdscr.getch()
            if key == -1:
                time.sleep(0.05)
                continue

            if key in (ord("q"), ord("Q")):
                return 0
            if key in (ord("a"), ord("A")):
                show_all = not show_all
                scroll = 0
            elif key in (ord("r"), ord("R")):
                next_refresh = 0.0
            elif key in (ord("+"), ord("=")):
                refresh_interval = min(60.0, refresh_interval + 0.5)
                next_refresh = 0.0
            elif key in (ord("-"), ord("_")):
                refresh_interval = max(0.5, refresh_interval - 0.5)
                next_refresh = 0.0
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                scroll += 1
            elif key in (curses.KEY_UP, ord("k"), ord("K")):
                scroll = max(0, scroll - 1)
            elif key in (curses.KEY_NPAGE,):
                scroll += 10
            elif key in (curses.KEY_PPAGE,):
                scroll = max(0, scroll - 10)

        return 0

    return curses.wrapper(_inner)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Terminal dashboard for BOINC tasks and resources (similar to htop view)."
    )
    parser.add_argument(
        "--boinccmd",
        default="boinccmd",
        help="Command used to invoke boinccmd (default: boinccmd).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Refresh interval in seconds (default: 2.0).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Start in all-tasks mode (default shows running tasks only).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot and exit (non-interactive).",
    )
    parser.add_argument(
        "--no-sudo-fallback",
        action="store_true",
        help="Do not try fallback command: sudo -n -u boinc boinccmd --get_tasks.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval < 0.5:
        print("--interval must be >= 0.5", file=sys.stderr)
        return 2

    try:
        task_cmd = shlex.split(args.boinccmd)
    except ValueError as exc:
        print(f"Invalid --boinccmd value: {exc}", file=sys.stderr)
        return 2

    if not task_cmd:
        print("--boinccmd may not be empty", file=sys.stderr)
        return 2

    if args.once:
        try:
            output = run_get_tasks_command(task_cmd, use_sudo_fallback=not args.no_sudo_fallback)
            tasks = parse_tasks(output)
            print_once(tasks, show_all=args.all)
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    try:
        return run_tui(task_cmd, show_all_initial=args.all, interval=args.interval, no_sudo_fallback=args.no_sudo_fallback)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
