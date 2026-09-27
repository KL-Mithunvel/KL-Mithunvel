#!/usr/bin/env python3
"""
Generates self-hosted GitHub stats SVG cards for the profile README,
replacing the github-readme-stats.vercel.app dependency.

Pulls data straight from the GitHub GraphQL/REST API and renders two
static SVGs into assets/. No third-party rendering service involved.

Env vars:
  GH_TOKEN     - GitHub token (GITHUB_TOKEN from Actions works fine)
  GH_USERNAME  - GitHub username to report on
"""

import datetime as dt
import math
import os
import sys

import requests

GRAPHQL_URL = "https://api.github.com/graphql"

# Colors GitHub uses for common languages; fallback color used otherwise.
LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "C++": "#f34b7d",
    "C": "#555555",
    "Verilog": "#b2b7f8",
    "Assembly": "#6E4C13",
    "SQL": "#e38c00",
    "Shell": "#89e051",
    "R": "#198CE7",
    "G-code": "#D08CF2",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Jupyter Notebook": "#DA5B0B",
    "CMake": "#DA3434",
    "Makefile": "#427819",
    "Dockerfile": "#384d54",
    "Vue": "#41b883",
    "Batchfile": "#C1F12E",
    "PowerShell": "#012456",
    "Tcl": "#e4cc98",
    "Java": "#b07219",
}
FALLBACK_COLOR = "#8b8b8b"
OTHER_COLOR = "#4b5563"  # distinct from FALLBACK_COLOR so an unrecognized
# top-6 language never renders identically to the aggregated "Other" slice

BG_COLOR = "#0d1117"
TITLE_COLOR = "#2d77dc"
TEXT_COLOR = "#ffffff"
SUBTEXT_COLOR = "#a1a1aa"
BAR_TRACK_COLOR = "#21262d"

CARD_WIDTH = 495


def gh_session():
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"bearer {token}",
            "Accept": "application/vnd.github+json",
        }
    )
    return session


def graphql(session, query, variables):
    resp = session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
  }
}
"""

CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
    }
  }
}
"""

REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: [OWNER], isFork: false, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        owner { login }
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
}
"""

COMMIT_HISTORY_QUERY = """
query($owner: String!, $name: String!, $authorId: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after, author: {id: $authorId}) {
            nodes { authoredDate }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }
  }
}
"""


def fetch_user(session, login):
    data = graphql(session, USER_QUERY, {"login": login})
    return data["user"]


def fetch_contribution_totals(session, login, created_at):
    """contributionsCollection is capped at ~1 year per call, so sum year by year."""
    start_year = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
    end_year = dt.datetime.now(dt.timezone.utc).year

    totals = {
        "commits": 0,
        "prs": 0,
        "issues": 0,
        "reviews": 0,
    }

    for year in range(start_year, end_year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z"
        data = graphql(session, CONTRIB_QUERY, {"login": login, "from": frm, "to": to})
        c = data["user"]["contributionsCollection"]
        totals["commits"] += c["totalCommitContributions"]
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        totals["reviews"] += c["totalPullRequestReviewContributions"]

    return totals


def fetch_repo_stats(session, login):
    total_stars = 0
    total_forks = 0
    repo_count = 0
    language_bytes = {}
    repos_list = []
    after = None

    while True:
        data = graphql(session, REPOS_QUERY, {"login": login, "after": after})
        repos = data["user"]["repositories"]
        repo_count = repos["totalCount"]

        for node in repos["nodes"]:
            total_stars += node["stargazerCount"]
            total_forks += node["forkCount"]
            repos_list.append((node["owner"]["login"], node["name"]))
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                language_bytes[name] = language_bytes.get(name, 0) + edge["size"]

        if repos["pageInfo"]["hasNextPage"]:
            after = repos["pageInfo"]["endCursor"]
        else:
            break

    return {
        "repo_count": repo_count,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "language_bytes": language_bytes,
        "repos": repos_list,
    }


def fetch_commit_hour_histogram(session, login, author_id, repos):
    """Buckets commit authored-times by hour of day (0-23), using each
    commit's recorded local time (git preserves the author's UTC offset)."""
    hour_counts = [0] * 24

    for owner, name in repos:
        after = None
        while True:
            data = graphql(
                session,
                COMMIT_HISTORY_QUERY,
                {"owner": owner, "name": name, "authorId": author_id, "after": after},
            )
            repo = data["repository"]
            target = repo["defaultBranchRef"]["target"] if repo and repo.get("defaultBranchRef") else None
            if not target:
                break

            history = target["history"]
            for node in history["nodes"]:
                authored = dt.datetime.fromisoformat(node["authoredDate"].replace("Z", "+00:00"))
                hour_counts[authored.hour] += 1

            if history["pageInfo"]["hasNextPage"]:
                after = history["pageInfo"]["endCursor"]
            else:
                break

    return hour_counts


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_stats_card(username, followers, contrib_totals, repo_stats):
    rows = [
        ("Total Stars", f"{repo_stats['total_stars']:,}"),
        ("Total Commits", f"{contrib_totals['commits']:,}"),
        ("Total PRs", f"{contrib_totals['prs']:,}"),
        ("Total Issues", f"{contrib_totals['issues']:,}"),
        ("PR Reviews", f"{contrib_totals['reviews']:,}"),
        ("Public Repos", f"{repo_stats['repo_count']:,}"),
        ("Followers", f"{followers:,}"),
    ]

    row_height = 34
    top_padding = 70
    height = top_padding + row_height * len(rows) + 20

    row_svgs = []
    for i, (label, value) in enumerate(rows):
        y = top_padding + i * row_height
        row_svgs.append(f"""
    <text x="25" y="{y}" class="stat-label">{esc(label)}:</text>
    <text x="{CARD_WIDTH - 25}" y="{y}" text-anchor="end" class="stat-value">{esc(value)}</text>""")

    return f"""<svg width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .card-bg {{ fill: {BG_COLOR}; }}
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TITLE_COLOR}; }}
    .stat-label {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {SUBTEXT_COLOR}; }}
    .stat-value {{ font: 600 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TEXT_COLOR}; }}
  </style>
  <rect x="0.5" y="0.5" rx="8" width="{CARD_WIDTH - 1}" height="{height - 1}" class="card-bg" stroke="none"/>
  <text x="25" y="35" class="title">{esc(username)}'s GitHub Stats</text>
  {''.join(row_svgs)}
</svg>
"""


def render_top_langs_card(language_bytes, max_langs=6):
    total = sum(language_bytes.values()) or 1
    ranked = sorted(language_bytes.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[:max_langs]
    other_size = sum(size for _, size in ranked[max_langs:])
    slices = list(top)
    if other_size > 0:
        slices.append(("Other", other_size))

    def slice_color(name):
        if name == "Other":
            return OTHER_COLOR
        return LANGUAGE_COLORS.get(name, FALLBACK_COLOR)

    # Pure-SVG pie via a thick circle stroke: a circle of radius R/2 stroked
    # with stroke-width R has its stroke span from the center out to R, so
    # each dasharray segment renders as a full wedge rather than a ring.
    outer_r = 95
    path_r = outer_r / 2
    circumference = 2 * math.pi * path_r
    cx = CARD_WIDTH / 2  # pie centered above the legend, not left-anchored

    top_padding = 55
    pie_to_legend_gap = 34
    row_height = 26
    bottom_padding = 20
    swatch_gap = 8
    label_pct_gap = 14
    avg_char_px = 7.6  # rough width of the 14px sans-serif legend font

    cy = top_padding + outer_r
    legend_start_y = cy + outer_r + pie_to_legend_gap

    height = legend_start_y + row_height * (len(slices) - 1) + row_height / 2 + bottom_padding

    wedges = []
    offset = 0.0
    for name, size in slices:
        pct = size / total * 100
        color = slice_color(name)
        arc_len = pct / 100 * circumference
        wedges.append(
            f'<circle cx="{cx}" cy="{cy:.2f}" r="{path_r}" fill="none" stroke="{color}" '
            f'stroke-width="{outer_r}" stroke-dasharray="{arc_len:.2f} {circumference:.2f}" '
            f'stroke-dashoffset="-{offset:.2f}"/>'
        )
        offset += arc_len

    # Each row is centered under the pie as its own unit (swatch + label +
    # percent), rather than aligned into left/right columns, since the row
    # widths vary a lot between a short name like "C++" and a long one.
    legend_rows = []
    for i, (name, size) in enumerate(slices):
        pct = size / total * 100
        color = slice_color(name)
        pct_text = f"{pct:.1f}%"
        label_w = len(name) * avg_char_px
        pct_w = len(pct_text) * avg_char_px
        row_w = 12 + swatch_gap + label_w + label_pct_gap + pct_w
        row_x = cx - row_w / 2
        label_x = row_x + 12 + swatch_gap
        pct_x = label_x + label_w + label_pct_gap
        y = legend_start_y + i * row_height
        legend_rows.append(f"""
    <rect x="{row_x:.2f}" y="{y - 9:.2f}" width="12" height="12" rx="3" fill="{color}"/>
    <text x="{label_x:.2f}" y="{y + 1:.2f}" class="lang-label">{esc(name)}</text>
    <text x="{pct_x:.2f}" y="{y + 1:.2f}" class="lang-pct">{pct_text}</text>""")

    return f"""<svg width="{CARD_WIDTH}" height="{height:.0f}" viewBox="0 0 {CARD_WIDTH} {height:.0f}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .card-bg {{ fill: {BG_COLOR}; }}
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TITLE_COLOR}; }}
    .lang-label {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TEXT_COLOR}; }}
    .lang-pct {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {SUBTEXT_COLOR}; }}
  </style>
  <rect x="0.5" y="0.5" rx="8" width="{CARD_WIDTH - 1}" height="{height - 1:.0f}" class="card-bg" stroke="none"/>
  <text x="25" y="35" class="title">Most Used Languages</text>
  <g transform="rotate(-90 {cx} {cy})">
    {''.join(wedges)}
  </g>
  {''.join(legend_rows)}
</svg>
"""


def render_commit_times_card(hour_counts):
    total = sum(hour_counts)
    max_count = max(hour_counts) or 1

    chart_height = 130
    top_padding = 60
    bottom_padding = 35
    height = top_padding + chart_height + bottom_padding

    left_pad = 25
    right_pad = 25
    chart_width = CARD_WIDTH - left_pad - right_pad
    bar_gap = 3
    bar_width = (chart_width - bar_gap * 23) / 24

    bars = []
    for hour, count in enumerate(hour_counts):
        bar_height = (count / max_count) * chart_height
        x = left_pad + hour * (bar_width + bar_gap)
        y = top_padding + (chart_height - bar_height)
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{max(bar_height, 1):.1f}" '
            f'rx="2" fill="{TITLE_COLOR}"/>'
        )

    baseline_y = top_padding + chart_height
    label_hours = {0: "12am", 6: "6am", 12: "12pm", 18: "6pm", 23: "11pm"}
    labels = []
    for hour, label in label_hours.items():
        x = left_pad + hour * (bar_width + bar_gap) + bar_width / 2
        labels.append(
            f'<text x="{x:.1f}" y="{baseline_y + 18}" text-anchor="middle" class="hour-label">{label}</text>'
        )

    return f"""<svg width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .card-bg {{ fill: {BG_COLOR}; }}
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TITLE_COLOR}; }}
    .subtitle {{ font: 400 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: {SUBTEXT_COLOR}; }}
    .hour-label {{ font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: {SUBTEXT_COLOR}; }}
  </style>
  <rect x="0.5" y="0.5" rx="8" width="{CARD_WIDTH - 1}" height="{height - 1}" class="card-bg" stroke="none"/>
  <text x="25" y="35" class="title">Commit Times of Day</text>
  <text x="{CARD_WIDTH - 25}" y="35" text-anchor="end" class="subtitle">{total:,} commits</text>
  <line x1="{left_pad}" y1="{baseline_y}" x2="{CARD_WIDTH - right_pad}" y2="{baseline_y}" stroke="{BAR_TRACK_COLOR}" stroke-width="1"/>
  {''.join(bars)}
  {''.join(labels)}
</svg>
"""


def main():
    username = os.environ.get("GH_USERNAME")
    if not username:
        print("GH_USERNAME is not set", file=sys.stderr)
        sys.exit(1)

    session = gh_session()

    user = fetch_user(session, username)
    contrib_totals = fetch_contribution_totals(session, username, user["createdAt"])
    repo_stats = fetch_repo_stats(session, username)
    hour_counts = fetch_commit_hour_histogram(session, username, user["id"], repo_stats["repos"])

    stats_svg = render_stats_card(username, user["followers"]["totalCount"], contrib_totals, repo_stats)
    langs_svg = render_top_langs_card(repo_stats["language_bytes"])
    commit_times_svg = render_commit_times_card(hour_counts)

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg)

    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg)

    with open(os.path.join(out_dir, "commit-times.svg"), "w", encoding="utf-8") as f:
        f.write(commit_times_svg)

    print("Stats generated.")


if __name__ == "__main__":
    main()
