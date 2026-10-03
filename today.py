"""Builds dark_mode.svg / light_mode.svg for the profile README (neofetch style).

Run by .github/workflows/update.yml every day. It refreshes the uptime line and
the GitHub Stats block, then regenerates both SVGs from the templates below.

    ACCESS_TOKEN=<token> python today.py        # fetch live stats, then build
    python today.py --offline                   # build from stats.json only

Only needs `requests`.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

USER = "riverorepo"
BIRTHDAY = datetime(1988, 4, 23)
LINE_WIDTH = 70          # characters per info line (keeps the dotted leaders aligned)
PORTRAIT_COLS = 96

# ---------------------------------------------------------------- info block --
# Each entry: ("key", "value") | ("header", "title") | ("blank",) | ("stats",)
# Dynamic values use {placeholders} filled from the stats dict.
INFO = [
    ("header", "ruben@rivero"),
    ("key", "OS", "Windows 11, macOS, Linux"),
    ("key", "Uptime", "{uptime}"),
    ("key", "Host", "Zelis"),
    ("key", "Kernel", "Lead Cloud Platform DevOps Engineer"),
    ("key", "IDE", "VS Code"),
    ("key", "Copilots", "Claude Code, Codex"),
    ("blank",),
    ("key", "Cloud", "AWS, GCP, Azure"),
    ("key", "Certs", "AWS Solutions Architect Professional"),
    ("key", "IaC", "Terraform, Python, AWS CDK"),
    ("key", "Platform", "EKS, Karpenter, ECS, GitHub Actions"),
    ("key", "Languages.Programming", "Python, HCL, Bash, PowerShell"),
    ("key", "Languages.Real", "English, Spanish"),
    ("key", "Compliance", "SOX, PCI, HIPAA"),
    ("blank",),
    ("key", "Hobbies.Software", "AI agents, MCP servers"),
    ("key", "Hobbies.Offline", "Brazilian Jiu Jitsu, boating, fishing, PC gaming"),
    ("blank",),
    ("header", "Contact"),
    ("key", "Email", "riveroemail@gmail.com"),
    ("key", "LinkedIn", "Ruben Rivero"),
    ("blank",),
    ("header", "GitHub Stats"),
    ("stats",),
]

THEMES = {
    "dark_mode.svg": dict(
        bg="#0d1117", art="#c9d1d9", key="#ffa657", val="#c9d1d9", dim="#8b949e",
        hdr="#f0f6fc", add="#3fb950", dele="#f85149", portrait="portrait_dark.txt"),
    "light_mode.svg": dict(
        bg="#ffffff", art="#24292f", key="#bc4c00", val="#1f2328", dim="#6e7781",
        hdr="#1f2328", add="#1a7f37", dele="#cf222e", portrait="portrait_light.txt"),
}


# ------------------------------------------------------------------- helpers --
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def uptime_text(now: datetime) -> str:
    y, m, d = now.year - BIRTHDAY.year, now.month - BIRTHDAY.month, now.day - BIRTHDAY.day
    if d < 0:
        m -= 1
        prev_month = now.month - 1 or 12
        prev_year = now.year if now.month > 1 else now.year - 1
        days_in_prev = (datetime(prev_year + (prev_month == 12), prev_month % 12 + 1, 1)
                        - datetime(prev_year, prev_month, 1)).days
        d += days_in_prev
    if m < 0:
        y -= 1
        m += 12
    return f"{y} years, {m} months, {d} days"


def fmt(n: int) -> str:
    return f"{n:,}"


# --------------------------------------------------------------------- stats --
def gql(query: str, variables: dict, token: str) -> dict:
    import requests
    r = requests.post("https://api.github.com/graphql",
                      json={"query": query, "variables": variables},
                      headers={"Authorization": f"bearer {token}"}, timeout=60)
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def rest(url: str, token: str):
    import requests
    for _ in range(8):                       # stats endpoints return 202 while computing
        r = requests.get(url, headers={"Authorization": f"bearer {token}"}, timeout=60)
        if r.status_code == 202:
            time.sleep(3)
            continue
        if r.status_code == 204:
            return []
        r.raise_for_status()
        return r.json()
    return []


def fetch_stats(token: str) -> dict:
    data = gql("""
        query($login: String!) {
          user(login: $login) {
            createdAt
            followers { totalCount }
            repositories(first: 100, ownerAffiliations: OWNER) {
              totalCount
              nodes { name isFork stargazerCount }
            }
            repositoriesContributedTo(first: 1, includeUserRepositories: true,
              contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) { totalCount }
          }
        }""", {"login": USER}, token)["user"]

    created = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    commits = 0
    for year in range(created.year, now.year + 1):
        start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        if start >= end:
            continue
        cc = gql("""
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  totalCommitContributions
                  restrictedContributionsCount
                }
              }
            }""", {"login": USER, "from": start.isoformat(), "to": end.isoformat()}, token
        )["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]

    additions = deletions = 0
    for repo in data["repositories"]["nodes"]:
        for c in rest(f"https://api.github.com/repos/{USER}/{repo['name']}/stats/contributors", token):
            if c.get("author") and c["author"]["login"].lower() == USER.lower():
                additions += sum(w["a"] for w in c["weeks"])
                deletions += sum(w["d"] for w in c["weeks"])

    return {
        "repos": data["repositories"]["totalCount"],
        "contributed": data["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in data["repositories"]["nodes"]),
        "commits": commits,
        "followers": data["followers"]["totalCount"],
        "additions": additions,
        "deletions": deletions,
        "updated": now.strftime("%Y-%m-%d"),
    }


# ----------------------------------------------------------------------- svg --
def leader(key: str, value: str) -> tuple[str, str, str]:
    """key + dotted leader + value, padded to LINE_WIDTH characters."""
    k = f"{key}: "
    dots = LINE_WIDTH - len(k) - len(value) - 1
    if dots < 2:                      # value too long: trim it rather than break the grid
        value = value[: LINE_WIDTH - len(k) - 3 - 1]
        dots = 2
    return k, "." * dots, " " + value


def header_line(title: str) -> tuple[str, str]:
    return title, " " + "─" * (LINE_WIDTH - len(title) - 1)


def stats_lines(s: dict, t: dict) -> list[str]:
    """Three stat lines, as SVG <text> inner markup."""
    def tsp(cls, text):
        return f'<tspan fill="{t[cls]}">{esc(text)}</tspan>'

    def padded(key, value, width):
        k = f"{key}: "
        dots = max(2, width - len(k) - len(value) - 1)
        return tsp("key", k) + tsp("dim", "." * dots) + tsp("val", " " + value)

    left1 = ("Repos", f"{fmt(s['repos'])} {{Contributed: {fmt(s['contributed'])}}}")
    left2 = ("Commits", fmt(s["commits"]))
    col = max(len(f"{k}: ") + len(v) + 3 for k, v in (left1, left2))   # left column width
    right_w = LINE_WIDTH - col - 3

    line1 = padded(*left1, col) + tsp("dim", " | ") + padded("Stars", fmt(s["stars"]), right_w)
    line2 = padded(*left2, col) + tsp("dim", " | ") + padded("Followers", fmt(s["followers"]), right_w)
    total = s["additions"] - s["deletions"]
    plain3 = (f"Lines of Code on GitHub: {fmt(total)} ( {fmt(s['additions'])}++, "
              f"{fmt(s['deletions'])}-- )")
    line3 = (tsp("key", "Lines of Code on GitHub: ") + tsp("val", f"{fmt(total)} ( ")
             + tsp("add", f"{fmt(s['additions'])}++") + tsp("val", ", ")
             + tsp("dele", f"{fmt(s['deletions'])}--") + tsp("val", " )")
             + tsp("val", " " * max(0, LINE_WIDTH - len(plain3))))
    return [line1, line2, line3]


def build_svg(stats: dict, theme: dict, out_path: str) -> None:
    with open(theme["portrait"], encoding="utf-8") as f:
        portrait = [ln.rstrip("\n").ljust(PORTRAIT_COLS) for ln in f.read().splitlines()]

    # geometry
    margin, gap = 32, 44
    info_fs, info_lh = 13.0, 17.5
    info_w = LINE_WIDTH * info_fs * 0.6
    info_h = info_lh * len(INFO) + 2 * info_lh   # "stats" expands to 3 lines
    cell_w = min(info_h / (2 * len(portrait)), 620 / PORTRAIT_COLS)
    art_w = cell_w * PORTRAIT_COLS
    art_lh = cell_w * 2                      # 2:1 cells, matches the converter's aspect
    art_fs = cell_w / 0.6
    art_h = art_lh * len(portrait)
    height = max(art_h, info_h) + 2 * margin
    width = margin + art_w + gap + info_w + margin
    art_x, info_x = margin, margin + art_w + gap
    art_y0 = (height - art_h) / 2 + art_lh * 0.8
    info_y0 = (height - info_h) / 2 + info_lh * 0.8

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" '
        'font-family="Consolas, \'DejaVu Sans Mono\', Menlo, \'Courier New\', monospace">',
        f'<rect width="100%" height="100%" rx="6" fill="{theme["bg"]}"/>',
        '<style>text { white-space: pre; }</style>',
        f'<g fill="{theme["art"]}" font-size="{art_fs:.2f}" xml:space="preserve">',
    ]
    for i, line in enumerate(portrait):
        out.append(f'<text x="{art_x}" y="{art_y0 + i * art_lh:.2f}" textLength="{art_w:.0f}" '
                   f'lengthAdjust="spacingAndGlyphs">{esc(line)}</text>')
    out.append("</g>")

    out.append(f'<g font-size="{info_fs}" xml:space="preserve">')
    y = info_y0
    values = {"uptime": uptime_text(datetime.now(timezone.utc).replace(tzinfo=None))}

    def text(inner, bold=False):
        nonlocal y
        weight = ' font-weight="bold"' if bold else ""
        out.append(f'<text x="{info_x}" y="{y:.2f}" textLength="{info_w:.0f}" '
                   f'lengthAdjust="spacing"{weight}>{inner}</text>')
        y += info_lh

    for item in INFO:
        kind = item[0]
        if kind == "blank":
            y += info_lh
        elif kind == "header":
            title, rule = header_line(item[1])
            text(f'<tspan fill="{theme["hdr"]}" font-weight="bold">{esc(title)}</tspan>'
                 f'<tspan fill="{theme["dim"]}">{esc(rule)}</tspan>')
        elif kind == "key":
            k, dots, v = leader(item[1], item[2].format(**values))
            text(f'<tspan fill="{theme["key"]}">{esc(k)}</tspan>'
                 f'<tspan fill="{theme["dim"]}">{dots}</tspan>'
                 f'<tspan fill="{theme["val"]}">{esc(v)}</tspan>')
        elif kind == "stats":
            for inner in stats_lines(stats, theme):
                text(inner)
    out.append("</g></svg>")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"wrote {out_path} ({width:.0f}x{height:.0f})")


def main() -> None:
    offline = "--offline" in sys.argv
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    stats = {}
    if os.path.exists("stats.json"):
        with open("stats.json", encoding="utf-8") as f:
            stats = json.load(f)
    if not offline and token:
        try:
            stats = fetch_stats(token)
            with open("stats.json", "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
            print("fetched live stats:", stats)
        except Exception as e:                     # keep the last good numbers
            print("stats fetch failed, using cached stats.json:", e, file=sys.stderr)
    if not stats:
        stats = {"repos": 0, "contributed": 0, "stars": 0, "commits": 0,
                 "followers": 0, "additions": 0, "deletions": 0}
    for name, theme in THEMES.items():
        build_svg(stats, theme, name)


if __name__ == "__main__":
    main()
