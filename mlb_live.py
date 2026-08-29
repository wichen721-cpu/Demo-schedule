#!/usr/bin/env python3
"""即時追蹤 MLB 比分的終端機 CLI 工具。

資料來源：MLB 官方公開 Stats API (https://statsapi.mlb.com/api/v1)
"""

import argparse
import sys
import time
from datetime import date

import requests
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.panel import Panel

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
REQUEST_TIMEOUT = 10

STATE_STYLE = {
    "Preview": ("未開打", "yellow"),
    "Pre-Game": ("賽前準備", "yellow"),
    "Warmup": ("熱身中", "yellow"),
    "In Progress": ("進行中", "bold green"),
    "Final": ("已結束", "bold white"),
    "Game Over": ("已結束", "bold white"),
    "Postponed": ("延賽", "red"),
    "Suspended": ("中斷", "red"),
    "Cancelled": ("取消", "red"),
}


def translate_state(detailed_state: str):
    return STATE_STYLE.get(detailed_state, (detailed_state, "white"))


class MLBApiError(Exception):
    pass


def fetch_schedule(target_date: str) -> list:
    """取得指定日期的所有賽事清單。"""
    params = {"sportId": 1, "date": target_date}
    try:
        resp = requests.get(SCHEDULE_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout as exc:
        raise MLBApiError(f"取得賽程逾時：{exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise MLBApiError(f"取得賽程失敗（連線問題）：{exc}") from exc
    except ValueError as exc:
        raise MLBApiError(f"賽程回應格式錯誤：{exc}") from exc

    games = []
    for day in data.get("dates", []):
        games.extend(day.get("games", []))
    return games


def fetch_live_feed(game_pk: int) -> dict:
    """取得單場比賽的即時逐局資訊。"""
    url = LIVE_FEED_URL.format(game_pk=game_pk)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout as exc:
        raise MLBApiError(f"取得即時資訊逾時：{exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise MLBApiError(f"取得即時資訊失敗（連線問題）：{exc}") from exc
    except ValueError as exc:
        raise MLBApiError(f"即時資訊回應格式錯誤：{exc}") from exc


def format_bases(matchup: dict) -> str:
    """把壘包跑者狀態畫成簡易圖示：一壘/二壘/三壘。"""
    postponed = {"first", "second", "third"}
    occupied = set()
    for base_key, runner_key in (
        ("first", "postOnFirst"),
        ("second", "postOnSecond"),
        ("third", "postOnThird"),
    ):
        if matchup.get(runner_key):
            occupied.add(base_key)

    def mark(base):
        return "●" if base in occupied else "○"

    return f"1壘{mark('first')} 2壘{mark('second')} 3壘{mark('third')}"


def build_linescore_summary(live_data: dict) -> dict:
    """從 live feed 擷取局數、出局數、好壞球數、壘包狀況、比分。"""
    live = live_data.get("liveData", {})
    linescore = live.get("linescore", {})
    plays = live.get("plays", {})
    current_play = plays.get("currentPlay", {})
    count = current_play.get("count", {})
    matchup = current_play.get("matchup", {})

    balls = count.get("balls", linescore.get("balls", 0))
    strikes = count.get("strikes", linescore.get("strikes", 0))
    outs = count.get("outs", linescore.get("outs", 0))

    inning_state = linescore.get("inningState", "")
    inning = linescore.get("currentInning", "")

    home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0)
    away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0)

    offense = linescore.get("offense", {}) or matchup
    bases_display = format_bases(offense)

    return {
        "inning": inning,
        "inning_state": inning_state,
        "balls": balls,
        "strikes": strikes,
        "outs": outs,
        "home_runs": home_runs,
        "away_runs": away_runs,
        "bases": bases_display,
    }


def render_table(games: list, fetch_details: bool, console: Console) -> Table:
    table = Table(title=f"MLB 賽事總覽 ({date.today().isoformat()})", expand=True)
    table.add_column("對戰組合", style="cyan", no_wrap=False)
    table.add_column("狀態", justify="center")
    table.add_column("比分", justify="center")
    table.add_column("局數", justify="center")
    table.add_column("出局數", justify="center")
    table.add_column("好壞球", justify="center")
    table.add_column("壘包狀況", justify="left")

    if not games:
        table.add_row("今天沒有排定的比賽", "-", "-", "-", "-", "-", "-")
        return table

    for game in games:
        try:
            teams = game.get("teams", {})
            away_name = teams.get("away", {}).get("team", {}).get("name", "?")
            home_name = teams.get("home", {}).get("team", {}).get("name", "?")
            matchup_label = f"{away_name} @ {home_name}"

            status = game.get("status", {})
            detailed_state = status.get("detailedState", "Unknown")
            state_label, state_style = translate_state(detailed_state)
            state_text = Text(state_label, style=state_style)

            away_score = teams.get("away", {}).get("score")
            home_score = teams.get("home", {}).get("score")
            score_label = (
                f"{away_score} - {home_score}"
                if away_score is not None and home_score is not None
                else "-"
            )

            inning_label = "-"
            outs_label = "-"
            count_label = "-"
            bases_label = "-"

            if fetch_details and detailed_state == "In Progress":
                game_pk = game.get("gamePk")
                try:
                    live_data = fetch_live_feed(game_pk)
                    summary = build_linescore_summary(live_data)
                    half = "上半" if summary["inning_state"] == "Top" else (
                        "下半" if summary["inning_state"] == "Bottom" else summary["inning_state"]
                    )
                    inning_label = f"第 {summary['inning']} 局 {half}"
                    outs_label = f"{summary['outs']} 出局"
                    count_label = f"{summary['balls']}-{summary['strikes']}"
                    bases_label = summary["bases"]
                    score_label = f"{summary['away_runs']} - {summary['home_runs']}"
                except MLBApiError as exc:
                    inning_label = "取得失敗"
                    console.log(f"[red]比賽 {game_pk} 即時資訊取得失敗：{exc}[/red]")

            table.add_row(
                matchup_label,
                state_text,
                score_label,
                inning_label,
                outs_label,
                count_label,
                bases_label,
            )
        except Exception as exc:  # noqa: BLE001 - 保護單場比賽解析失敗不影響整體
            console.log(f"[red]解析比賽資料時發生錯誤，已略過：{exc}[/red]")
            continue

    return table


def run_once(target_date: str, console: Console) -> None:
    try:
        games = fetch_schedule(target_date)
    except MLBApiError as exc:
        console.print(Panel(f"[red]{exc}[/red]", title="錯誤"))
        return
    table = render_table(games, fetch_details=True, console=console)
    console.print(table)


def run_polling(target_date: str, interval: int, console: Console) -> None:
    console.print(f"[bold]開始輪詢模式，每 {interval} 秒更新一次（Ctrl+C 結束）...[/bold]")
    try:
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                try:
                    games = fetch_schedule(target_date)
                    table = render_table(games, fetch_details=True, console=console)
                except MLBApiError as exc:
                    table = Panel(f"[red]{exc}[/red]", title="錯誤，將於下次輪詢重試")
                live.update(table)
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]已停止輪詢。[/bold yellow]")


def main() -> None:
    parser = argparse.ArgumentParser(description="即時追蹤 MLB 比分的終端機工具")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="要查詢的日期，格式 YYYY-MM-DD，預設為今天",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="啟用自動輪詢模式，每隔指定秒數更新畫面",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="輪詢模式的更新間隔秒數，預設 15 秒",
    )
    args = parser.parse_args()

    console = Console()

    try:
        if args.watch:
            run_polling(args.date, args.interval, console)
        else:
            run_once(args.date, console)
    except Exception as exc:  # noqa: BLE001 - 最外層防護，避免任何未預期例外導致崩潰
        console.print(Panel(f"[red]發生未預期的錯誤：{exc}[/red]", title="致命錯誤"))
        sys.exit(1)


if __name__ == "__main__":
    main()
