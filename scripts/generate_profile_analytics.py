#!/usr/bin/env python3
"""Generate GitHub profile analytics SVGs from GitHub's GraphQL API.

Requires GH_TOKEN (prefer a PAT with read:user and repo scopes when private
contributions/repos should be included) and GITHUB_LOGIN.
Only reads GitHub data and writes SVG files inside ./profile.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

API_URL = "https://api.github.com/graphql"
TZ = ZoneInfo("Asia/Kolkata")
OUT = Path("profile")
BG = "#0D1117"
PANEL = "#161B22"
BORDER = "#30363D"
TEXT = "#E6EDF3"
MUTED = "#9DA7B3"
GREEN = "#39D353"
BLUE = "#58A6FF"
PURPLE = "#BC8CFF"
ORANGE = "#F0883E"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!, $cursor: String) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        nameWithOwner
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def graphql(token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-analytics-generator",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"GitHub GraphQL returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub GraphQL: {exc.reason}") from exc
    if result.get("errors"):
        messages = "; ".join(e.get("message", "GraphQL error") for e in result["errors"])
        raise RuntimeError(messages)
    return result.get("data", {})


def esc(value: object) -> str:
    return escape(str(value))


def svg_start(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">',
        '<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#39D353" stop-opacity="0.30"/><stop offset="100%" stop-color="#39D353" stop-opacity="0.015"/></linearGradient></defs>',
        f'<rect width="{width}" height="{height}" rx="18" fill="{BG}" stroke="{BORDER}"/>',
    ]


def svg_text(x: float, y: float, text: str, size: int = 16, color: str = TEXT,
             weight: int = 400, anchor: str = "start") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" '
            f'font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{esc(text)}</text>')


def load_calendar(collection: dict, start_day: date, end_day: date) -> list[tuple[date, int]]:
    counts: dict[date, int] = {}
    calendar = collection.get("contributionCalendar", {})
    for week in calendar.get("weeks", []):
        for item in week.get("contributionDays", []):
            try:
                counts[date.fromisoformat(item["date"])] = int(item.get("contributionCount", 0))
            except (KeyError, ValueError, TypeError):
                continue
    rows = []
    d = start_day
    while d <= end_day:
        rows.append((d, counts.get(d, 0)))
        d += timedelta(days=1)
    return rows


def streak_lengths(rows: list[tuple[date, int]], today: date) -> tuple[int, int]:
    longest = run = 0
    for _, count in rows:
        run = run + 1 if count > 0 else 0
        longest = max(longest, run)

    # GitHub's streak convention keeps yesterday's active run current until
    # the current local day has ended; otherwise count back from today.
    end_index = len(rows) - 1
    if rows and rows[-1][0] == today and rows[-1][1] == 0:
        end_index -= 1
    current = 0
    for i in range(end_index, -1, -1):
        if rows[i][1] <= 0:
            break
        current += 1
    return current, longest


def write_streak(rows: list[tuple[date, int]], total: int, current: int, longest: int) -> None:
    width, height = 1100, 220
    parts = svg_start(width, height, "Daily GitHub Contribution Streak")
    parts.append(svg_text(34, 42, "DAILY CONTRIBUTION STREAK", 15, MUTED, 700))
    parts.append(svg_text(34, 112, f"{total:,}", 36, TEXT, 700))
    parts.append(svg_text(34, 142, "Contributions · last 12 months", 14, MUTED))
    # Decorative divider lines and simple labels keep the card recruiter-friendly.
    for x in (380, 730):
        parts.append(f'<line x1="{x}" y1="66" x2="{x}" y2="174" stroke="{BORDER}"/>')
    metrics = [(555, current, "Current streak"), (900, longest, "Longest streak")]
    for x, value, label in metrics:
        parts.append(svg_text(x, 116, f"{value:,}", 38, GREEN, 700, "middle"))
        parts.append(svg_text(x, 146, "days", 14, MUTED, 600, "middle"))
        parts.append(svg_text(x, 174, label, 15, TEXT, 600, "middle"))
    parts.append(svg_text(34, 194, "GitHub profile contributions · refreshed daily", 11, MUTED))
    parts.append("</svg>")
    (OUT / "streak.svg").write_text("\n".join(parts), encoding="utf-8")


def write_activity(rows: list[tuple[date, int]]) -> None:
    rows = rows[-90:]
    width, height = 1100, 360
    left, right, top, bottom = 66, 34, 58, 62
    plot_w, plot_h = width - left - right, height - top - bottom
    max_value = max((v for _, v in rows), default=1)
    # Round the scale to a readable interval.
    step = 1 if max_value <= 5 else (2 if max_value <= 20 else 5)
    y_max = max(step * 3, ((max_value + step - 1) // step) * step)
    parts = svg_start(width, height, "Daily GitHub Contributions · Last 90 Days")
    parts.append(svg_text(34, 34, "DAILY CONTRIBUTIONS · LAST 90 DAYS", 15, MUTED, 700))

    for value in range(0, y_max + 1, step):
        y = top + plot_h - (value / y_max) * plot_h
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="{BORDER}" stroke-dasharray="3 5"/>')
        parts.append(svg_text(left - 14, y + 5, str(value), 12, MUTED, 400, "end"))

    coords = []
    for i, (day, value) in enumerate(rows):
        x = left + (i / max(1, len(rows) - 1)) * plot_w
        y = top + plot_h - (value / y_max) * plot_h
        coords.append((x, y, day, value))

    if coords:
        line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
        area_points = f"{coords[0][0]:.1f},{top+plot_h} " + line_points + f" {coords[-1][0]:.1f},{top+plot_h}"
        parts.append(f'<polygon points="{area_points}" fill="url(#area)"/>')
        parts.append(f'<polyline points="{line_points}" fill="none" stroke="{GREEN}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y, day, value in coords:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{GREEN}" stroke="{BG}" stroke-width="1.5"><title>{esc(day.isoformat())}: {value} contributions</title></circle>')

    # Show only month labels, not 90 crowded day-of-month labels.
    seen_months = set()
    for i, (day, _) in enumerate(rows):
        month_key = (day.year, day.month)
        if month_key not in seen_months:
            seen_months.add(month_key)
            x = left + (i / max(1, len(rows) - 1)) * plot_w
            parts.append(svg_text(x, height - 24, day.strftime("%b %Y"), 12, MUTED, 500, "middle"))

    parts.append(svg_text(width - right, height - 24, "Day", 11, MUTED, 400, "end"))
    parts.append("</svg>")
    (OUT / "activity.svg").write_text("\n".join(parts), encoding="utf-8")


def write_stats(collection: dict) -> None:
    commits = int(collection.get("totalCommitContributions", 0))
    prs = int(collection.get("totalPullRequestContributions", 0))
    issues = int(collection.get("totalIssueContributions", 0))
    total = int(collection.get("contributionCalendar", {}).get("totalContributions", 0))
    metrics = [
        ("COMMITS", commits, GREEN),
        ("PULL REQUESTS", prs, BLUE),
        ("ISSUES", issues, PURPLE),
        ("TOTAL CONTRIBUTIONS", total, ORANGE),
    ]
    width, height = 1100, 210
    parts = svg_start(width, height, "GitHub Activity Summary · Last 12 Months")
    parts.append(svg_text(32, 38, "GITHUB ACTIVITY SUMMARY", 15, MUTED, 700))
    cell_w = (width - 64) / 4
    for i, (label, value, color) in enumerate(metrics):
        x = 32 + i * cell_w
        if i:
            parts.append(f'<line x1="{x:.1f}" y1="62" x2="{x:.1f}" y2="172" stroke="{BORDER}"/>')
        parts.append(f'<rect x="{x+18:.1f}" y="66" width="5" height="66" rx="2.5" fill="{color}"/>')
        parts.append(svg_text(x + 38, 105, f"{value:,}", 31, TEXT, 700))
        parts.append(svg_text(x + 38, 132, label, 12, MUTED, 700))
    parts.append(svg_text(32, 181, "GitHub-attributed activity · rolling 12-month window", 11, MUTED))
    parts.append("</svg>")
    (OUT / "stats.svg").write_text("\n".join(parts), encoding="utf-8")


def write_languages(repo_nodes: list[dict]) -> None:
    totals: dict[str, int] = defaultdict(int)
    colors: dict[str, str] = {}
    for repo in repo_nodes:
        for edge in repo.get("languages", {}).get("edges", []):
            lang = edge.get("node", {}).get("name")
            size = int(edge.get("size", 0) or 0)
            if lang and size > 0:
                totals[lang] += size
                colors[lang] = edge.get("node", {}).get("color") or BLUE

    top = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]
    width, height = 1100, max(230, 94 + len(top) * 26)
    parts = svg_start(width, height, "Most Used Languages in Owned Non-fork Repositories")
    parts.append(svg_text(32, 38, "MOST USED LANGUAGES", 15, MUTED, 700))
    grand = sum(totals.values()) or 1
    bar_x, bar_w = 270, 760
    for idx, (lang, value) in enumerate(top):
        y = 80 + idx * 26
        pct = value / grand * 100
        color = colors.get(lang, BLUE)
        parts.append(svg_text(34, y + 13, lang, 13, TEXT, 600))
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="12" rx="6" fill="{PANEL}"/>')
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{bar_w*pct/100:.1f}" height="12" rx="6" fill="{color}"/>')
        parts.append(svg_text(1050, y + 12, f"{pct:.1f}%", 12, MUTED, 500, "end"))
    if not top:
        parts.append(svg_text(width / 2, 115, "No language data available from accessible repositories", 14, MUTED, 400, "middle"))
    parts.append(svg_text(32, height - 22, "Based on language bytes in owned, non-fork repositories", 11, MUTED))
    parts.append("</svg>")
    (OUT / "languages.svg").write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    token = os.environ.get("GH_TOKEN", "").strip()
    login = os.environ.get("GITHUB_LOGIN", "").strip()
    if not token or not login:
        print("GH_TOKEN and GITHUB_LOGIN are required", file=sys.stderr)
        return 2

    today = datetime.now(TZ).date()
    start_day = today - timedelta(days=364)
    start_dt = datetime.combine(start_day, time.min, TZ).isoformat()
    end_dt = datetime.combine(today, time.max.replace(microsecond=0), TZ).isoformat()

    all_repo_nodes: list[dict] = []
    cursor = None
    collection = None
    while True:
        data = graphql(token, {
            "query": QUERY,
            "variables": {"login": login, "from": start_dt, "to": end_dt, "cursor": cursor},
        })
        user = data.get("user")
        if not user:
            raise RuntimeError(f"GitHub user '{login}' was not found or is not accessible")
        if collection is None:
            collection = user["contributionsCollection"]
        repos = user.get("repositories", {})
        all_repo_nodes.extend(repos.get("nodes", []))
        page = repos.get("pageInfo", {})
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
        if not cursor:
            raise RuntimeError("Repository pagination returned hasNextPage without an endCursor")

    rows = load_calendar(collection, start_day, today)
    current, longest = streak_lengths(rows, today)
    OUT.mkdir(parents=True, exist_ok=True)
    write_streak(rows, int(collection.get("contributionCalendar", {}).get("totalContributions", 0)), current, longest)
    write_activity(rows)
    write_stats(collection)
    write_languages(all_repo_nodes)
    print(f"Generated analytics for @{login}: {len(rows)} contribution days, {len(all_repo_nodes)} owned non-fork repositories; current streak={current} days, longest={longest} days")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Analytics generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
