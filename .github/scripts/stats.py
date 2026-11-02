#!/usr/bin/env python3
"""Generate profile stat cards (stats, languages, streak) as SVG files.

Runs inside GitHub Actions with the built-in GITHUB_TOKEN, so no personal
token or third-party service is needed. Standard library only.

Usage:  python stats.py <github-login> <output-dir>
        python stats.py --demo <output-dir>     (render with sample data)
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from html import escape

# ── Theme (matches the README header/footer colours) ────────────────────────
BG, BORDER = "#0d1117", "#21262d"
TITLE, TEXT, MUTED = "#58a6ff", "#c9d1d9", "#8b949e"
ACCENT, ACCENT2 = "#7c3aed", "#1f6feb"
FONT = "'Segoe UI', Ubuntu, -apple-system, sans-serif"

API = "https://api.github.com/graphql"

# Markup/config/shell languages skew the chart, so they are left out.
IGNORED_LANGS = {"HTML", "CSS", "SCSS", "Shell", "PowerShell", "Dockerfile",
                 "Makefile", "Batchfile", "Procfile"}


# ── Data fetching ───────────────────────────────────────────────────────────
def gql(query, variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


PROFILE_Q = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalIssueContributions
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}"""


def fetch(login):
    user = gql(PROFILE_Q, {"login": login})["user"]
    repos = user["repositories"]["nodes"]

    langs = {}
    for repo in repos:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name in IGNORED_LANGS:
                continue
            entry = langs.setdefault(name, {"size": 0, "color": e["node"]["color"] or MUTED})
            entry["size"] += e["size"]

    # Contribution calendar, one year at a time (API limit), since account creation.
    days, commits, prs, issues = {}, 0, 0, 0
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    cursor = start
    while cursor < now:
        end = min(cursor + dt.timedelta(days=365), now)
        c = gql(YEAR_Q, {"login": login, "from": cursor.isoformat(), "to": end.isoformat()})
        c = c["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        prs += c["totalPullRequestContributions"]
        issues += c["totalIssueContributions"]
        for w in c["contributionCalendar"]["weeks"]:
            for d in w["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        cursor = end

    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "repos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "langs": langs,
        "days": days,
        "since": start.date(),
    }


# ── Streak maths ────────────────────────────────────────────────────────────
def streaks(days):
    dates = sorted(days)
    total = sum(days.values())
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d] > 0 else 0
        longest = max(longest, run)

    # Current streak: count back from today; a zero "today" doesn't break it yet.
    current, i = 0, len(dates) - 1
    if i >= 0 and days[dates[i]] == 0:
        i -= 1
    while i >= 0 and days[dates[i]] > 0:
        current += 1
        i -= 1
    return total, current, longest


# ── SVG helpers ─────────────────────────────────────────────────────────────
def card(width, height, title, body):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .t {{ font: 600 18px {FONT}; fill: {TITLE}; }}
  .l {{ font: 400 14px {FONT}; fill: {TEXT}; }}
  .v {{ font: 700 14px {FONT}; fill: {TEXT}; }}
  .m {{ font: 400 12px {FONT}; fill: {MUTED}; }}
  .big {{ font: 700 28px {FONT}; fill: {TEXT}; }}
  .fade {{ opacity: 0; animation: f .6s ease-in-out forwards; }}
  @keyframes f {{ to {{ opacity: 1; }} }}
</style>
<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT2}"/><stop offset="1" stop-color="{ACCENT}"/></linearGradient></defs>
<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" fill="{BG}" stroke="{BORDER}"/>
<text x="25" y="38" class="t">{escape(title)}</text>
{body}
</svg>"""


def fmt(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def stats_svg(s):
    rows = [
        ("⭐", "Total Stars", s["stars"]),
        ("📝", "Total Commits", s["commits"]),
        ("🔀", "Pull Requests", s["prs"]),
        ("❗", "Issues", s["issues"]),
        ("📦", "Public Repos", s["repos"]),
        ("👥", "Followers", s["followers"]),
    ]
    body = ""
    for i, (icon, label, val) in enumerate(rows):
        y = 75 + i * 27
        body += (
            f'<g class="fade" style="animation-delay:{i*120}ms">'
            f'<rect x="25" y="{y-10}" width="10" height="10" rx="3" fill="url(#g)"/>'
            f'<text x="45" y="{y}" class="l">{label}</text>'
            f'<text x="225" y="{y}" class="v">{fmt(val)}</text></g>\n'
        )
    # Decorative ring with total contributions
    body += (
        f'<circle cx="355" cy="125" r="48" fill="none" stroke="{BORDER}" stroke-width="7"/>'
        f'<circle cx="355" cy="125" r="48" fill="none" stroke="url(#g)" stroke-width="7" '
        f'stroke-linecap="round" stroke-dasharray="301" stroke-dashoffset="0" transform="rotate(-90 355 125)"/>'
        f'<text x="355" y="128" text-anchor="middle" class="big">{fmt(sum(s["days"].values()))}</text>'
        f'<text x="355" y="150" text-anchor="middle" class="m" style="font-size:11px">contributions</text>'
    )
    return card(445, 245, "GitHub Stats", body)


def langs_svg(langs, top=8):
    items = sorted(langs.items(), key=lambda kv: kv[1]["size"], reverse=True)[:top]
    total = sum(v["size"] for _, v in items) or 1
    width, bar_w = 445, 395

    # Stacked progress bar
    body, x = f'<clipPath id="c"><rect x="25" y="55" width="{bar_w}" height="10" rx="5"/></clipPath><g clip-path="url(#c)">', 25.0
    for _, v in items:
        w = bar_w * v["size"] / total
        body += f'<rect x="{x:.2f}" y="55" width="{w + 0.5:.2f}" height="10" fill="{v["color"]}"/>'
        x += w
    body += "</g>\n"

    # Two-column legend
    for i, (name, v) in enumerate(items):
        col, row = i % 2, i // 2
        cx, cy = 30 + col * 200, 95 + row * 30
        pct = 100 * v["size"] / total
        body += (
            f'<g class="fade" style="animation-delay:{i*100}ms">'
            f'<circle cx="{cx}" cy="{cy-5}" r="5" fill="{v["color"]}"/>'
            f'<text x="{cx+12}" y="{cy}" class="l">{escape(name)}</text>'
            f'<text x="{cx+175}" y="{cy}" text-anchor="end" class="m">{pct:.1f}%</text></g>\n'
        )
    if not items:
        body += '<text x="25" y="100" class="m">No public code yet.</text>'
    height = 245
    return card(width, height, "Most Used Languages", body)


def streak_svg(days, since):
    total, current, longest = streaks(days)
    cols = [
        (fmt(total), "Total Contributions", f"since {since:%b %Y}"),
        (str(current), "Current Streak", "days in a row"),
        (str(longest), "Longest Streak", "days"),
    ]
    width, colw = 600, 200
    body = ""
    for i, (num, label, sub) in enumerate(cols):
        cx = colw * i + colw / 2
        hl = i == 1
        if hl:  # flame ring around the current streak
            body += (
                f'<circle cx="{cx}" cy="105" r="42" fill="none" stroke="url(#g)" stroke-width="5"/>'
            )
        body += (
            f'<g class="fade" style="animation-delay:{i*150}ms">'
            f'<text x="{cx}" y="115" text-anchor="middle" class="big">{num}</text>'
            f'<text x="{cx}" y="172" text-anchor="middle" class="v" fill="{TITLE if hl else TEXT}">{label}</text>'
            f'<text x="{cx}" y="192" text-anchor="middle" class="m">{sub}</text></g>\n'
        )
        if i:
            body += f'<line x1="{colw*i}" y1="65" x2="{colw*i}" y2="190" stroke="{BORDER}"/>'
    svg = card(width, 215, "", body)
    return svg.replace(f'<text x="25" y="38" class="t"></text>\n', "")


# ── Main ────────────────────────────────────────────────────────────────────
def demo():
    today = dt.date.today()
    days = {str(today - dt.timedelta(days=i)): (3 if i < 6 or 20 < i < 32 else 0) for i in range(120)}
    return {
        "stars": 12, "repos": 9, "followers": 34, "commits": 412, "prs": 18, "issues": 5,
        "langs": {"TypeScript": {"size": 50000, "color": "#3178c6"},
                  "JavaScript": {"size": 30000, "color": "#f1e05a"},
                  "Python": {"size": 12000, "color": "#3572A5"},
                  "Java": {"size": 6000, "color": "#b07219"},
                  "C++": {"size": 4000, "color": "#f34b7d"},
                  "PHP": {"size": 1500, "color": "#4F5D95"}},
        "days": days, "since": today - dt.timedelta(days=120),
    }


if __name__ == "__main__":
    if sys.argv[1] == "--demo":
        data, out = demo(), sys.argv[2]
    else:
        data, out = fetch(sys.argv[1]), sys.argv[2]
    os.makedirs(out, exist_ok=True)
    files = {
        "stats.svg": stats_svg(data),
        "languages.svg": langs_svg(data["langs"]),
        "streak.svg": streak_svg(data["days"], data["since"]),
    }
    for name, svg in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", name)
