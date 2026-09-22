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
}
FALLBACK_COLOR = "#8b8b8b"

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
    after = None

    while True:
        data = graphql(session, REPOS_QUERY, {"login": login, "after": after})
        repos = data["user"]["repositories"]
        repo_count = repos["totalCount"]

        for node in repos["nodes"]:
            total_stars += node["stargazerCount"]
            total_forks += node["forkCount"]
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
    }


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


def render_top_langs_card(language_bytes, max_langs=8):
    total = sum(language_bytes.values()) or 1
    top = sorted(language_bytes.items(), key=lambda kv: kv[1], reverse=True)[:max_langs]

    bar_height = 10
    row_height = 38
    top_padding = 65
    height = top_padding + row_height * len(top) + 20

    bar_max_width = CARD_WIDTH - 50

    rows = []
    for i, (name, size) in enumerate(top):
        pct = size / total * 100
        color = LANGUAGE_COLORS.get(name, FALLBACK_COLOR)
        y = top_padding + i * row_height
        bar_width = max(bar_max_width * (size / total), 3)
        rows.append(f"""
    <text x="25" y="{y}" class="lang-label">{esc(name)}</text>
    <text x="{CARD_WIDTH - 25}" y="{y}" text-anchor="end" class="lang-pct">{pct:.1f}%</text>
    <rect x="25" y="{y + 8}" width="{bar_max_width}" height="{bar_height}" rx="5" fill="{BAR_TRACK_COLOR}"/>
    <rect x="25" y="{y + 8}" width="{bar_width:.1f}" height="{bar_height}" rx="5" fill="{color}"/>""")

    return f"""<svg width="{CARD_WIDTH}" height="{height}" viewBox="0 0 {CARD_WIDTH} {height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .card-bg {{ fill: {BG_COLOR}; }}
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TITLE_COLOR}; }}
    .lang-label {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TEXT_COLOR}; }}
    .lang-pct {{ font: 400 14px 'Segoe UI', Ubuntu, Sans-Serif; fill: {SUBTEXT_COLOR}; }}
  </style>
  <rect x="0.5" y="0.5" rx="8" width="{CARD_WIDTH - 1}" height="{height - 1}" class="card-bg" stroke="none"/>
  <text x="25" y="35" class="title">Most Used Languages</text>
  {''.join(rows)}
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

    stats_svg = render_stats_card(username, user["followers"]["totalCount"], contrib_totals, repo_stats)
    langs_svg = render_top_langs_card(repo_stats["language_bytes"])

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(stats_svg)

    with open(os.path.join(out_dir, "top-langs.svg"), "w", encoding="utf-8") as f:
        f.write(langs_svg)

    print("Stats generated.")


if __name__ == "__main__":
    main()
