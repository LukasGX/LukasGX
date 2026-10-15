import os
import sys
import time
from collections import defaultdict

import requests

GITHUB_API = "https://api.github.com"
API_VERSION = "2026-03-10"

USERNAME = "LukasGX"
TOKEN = os.environ.get("ACCESS_TOKEN")


if not USERNAME:
    print("ERROR: GITHUB_USERNAME is not set.", file=sys.stderr)
    sys.exit(1)

if not TOKEN:
    print("ERROR: GITHUB_TOKEN is not set.", file=sys.stderr)
    sys.exit(1)


session = requests.Session()
session.headers.update(
    {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": API_VERSION,
    }
)


def github_get(url, **params):
    """
    Perform a GET request against the GitHub API.

    GitHub's statistics endpoints may initially return HTTP 202
    while GitHub calculates the statistics, so retry those requests.
    """
    for attempt in range(10):
        response = session.get(url, params=params, timeout=30)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 202:
            time.sleep(min(2 + attempt * 2, 10))
            continue

        if response.status_code == 204:
            return None

        print(
            f"GitHub API error {response.status_code}: "
            f"{response.text}",
            file=sys.stderr,
        )
        response.raise_for_status()

    raise RuntimeError(f"GitHub statistics were not ready: {url}")


def get_repositories():
    """
    Get all repositories visible to the authenticated user.

    This includes public and private repositories.
    """
    repositories = []

    page = 1

    while True:
        data = github_get(
            f"{GITHUB_API}/user/repos",
            visibility="all",
            affiliation="owner,collaborator,organization_member",
            per_page=100,
            page=page,
        )

        if not data:
            break

        repositories.extend(data)

        if len(data) < 100:
            break

        page += 1

    return repositories


def get_contributor_stats(owner, repo):
    """
    Get contributor statistics for one repository.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/stats/contributors"

    try:
        return github_get(url) or []
    except requests.HTTPError as exc:
        # Repositories with 10,000+ commits cannot provide the
        # normal contributor statistics endpoint.
        if exc.response is not None and exc.response.status_code == 422:
            print(
                f"WARNING: contributor statistics unavailable for "
                f"{owner}/{repo}",
                file=sys.stderr,
            )
            return []

        raise


def get_languages(owner, repo):
    """
    Get GitHub's detected language byte counts for one repository.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/languages"

    try:
        return github_get(url) or {}
    except requests.HTTPError:
        print(
            f"WARNING: language statistics unavailable for "
            f"{owner}/{repo}",
            file=sys.stderr,
        )
        return {}


def calculate_statistics(repositories):
    """
    Aggregate commit, addition, deletion and language statistics.
    """

    total_commits = 0
    total_added = 0
    total_deleted = 0

    languages = defaultdict(int)

    for repository in repositories:
        owner = repository["owner"]["login"]
        name = repository["name"]

        print(f"Processing repository: {owner}/{name}")

        # ---------------------------------------------------------
        # Commit / line statistics
        # ---------------------------------------------------------

        contributors = get_contributor_stats(owner, name)

        for contributor in contributors:
            author = contributor.get("author")

            if not author:
                continue

            if author.get("login", "").lower() != USERNAME.lower():
                continue

            total_commits += contributor.get("total", 0)

            for week in contributor.get("weeks", []):
                total_added += week.get("a", 0)
                total_deleted += week.get("d", 0)

            break

        # ---------------------------------------------------------
        # Language statistics
        # ---------------------------------------------------------

        repo_languages = get_languages(owner, name)

        for language, byte_count in repo_languages.items():
            languages[language] += byte_count

    total_net = total_added - total_deleted

    return {
        "commits": total_commits,
        "added": total_added,
        "deleted": total_deleted,
        "net": total_net,
        "languages": dict(languages),
    }


def calculate_language_percentages(languages):
    """
    Convert GitHub's language byte counts into percentages.
    """

    total = sum(languages.values())

    if total == 0:
        return {}

    return {
        language: (bytes_ / total) * 100
        for language, bytes_ in languages.items()
    }

def generate_stats_svg(statistics, output_path="github-stats.svg"):
    """
    Generate a GitHub-theme-aware SVG containing the coding statistics.
    """

    language_percentages = calculate_language_percentages(
        statistics["languages"]
    )

    languages = [
        (language, percentage)
        for language, percentage in sorted(
            language_percentages.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if percentage >= 0.1
    ]

    width = 900
    row_height = 34
    top_height = 175
    language_header_height = 65
    bottom_padding = 30

    height = (
        top_height
        + language_header_height
        + len(languages) * row_height
        + bottom_padding
    )

    max_bar_width = 500

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',

        # -----------------------------------------------------
        # Theme
        # -----------------------------------------------------

        """
        <style>
            .background {
                fill: #ffffff;
            }

            .primary {
                fill: #24292f;
            }

            .secondary {
                fill: #57606a;
            }

            .bar-background {
                fill: #eaeef2;
            }

            .bar {
                fill: #0969da;
            }

            @media (prefers-color-scheme: dark) {
                .background {
                    fill: #0d1117;
                }

                .primary {
                    fill: #ffffff;
                }

                .secondary {
                    fill: #8b949e;
                }

                .bar-background {
                    fill: #21262d;
                }

                .bar {
                    fill: #58a6ff;
                }
            }
        </style>
        """,

        # -----------------------------------------------------
        # Background
        # -----------------------------------------------------

        '<rect width="100%" height="100%" rx="16" '
        'class="background"/>',

        # -----------------------------------------------------
        # Title
        # -----------------------------------------------------

        '<text x="40" y="52" '
        'font-family="Arial, Helvetica, sans-serif" '
        'font-size="26" font-weight="700" '
        'class="primary">CODING STATISTICS</text>',
    ]

    # ---------------------------------------------------------
    # Main statistics
    # ---------------------------------------------------------

    stats = [
        ("COMMITS", statistics["commits"]),
        ("LINES ADDED", statistics["added"]),
        ("LINES DELETED", statistics["deleted"]),
        ("NET LINES", statistics["net"]),
    ]

    stat_width = width / len(stats)

    for index, (label, value) in enumerate(stats):
        x = stat_width * index + stat_width / 2

        svg.append(
            f'<text x="{x}" y="105" text-anchor="middle" '
            f'font-family="Arial, Helvetica, sans-serif" '
            f'font-size="25" font-weight="700" '
            f'class="primary">{value:,}</text>'
        )

        svg.append(
            f'<text x="{x}" y="128" text-anchor="middle" '
            f'font-family="Arial, Helvetica, sans-serif" '
            f'font-size="11" letter-spacing="0.5" '
            f'class="secondary">{label}</text>'
        )

    # ---------------------------------------------------------
    # Languages header
    # ---------------------------------------------------------

    language_y = top_height

    svg.append(
        f'<text x="40" y="{language_y}" '
        f'font-family="Arial, Helvetica, sans-serif" '
        f'font-size="19" font-weight="700" '
        f'class="primary">LANGUAGES</text>'
    )

    y = language_y + language_header_height

    # ---------------------------------------------------------
    # Language rows
    # ---------------------------------------------------------

    for language, percentage in languages:
        bar_width = max_bar_width * (percentage / 100)

        svg.append(
            f'<text x="40" y="{y}" '
            f'font-family="Arial, Helvetica, sans-serif" '
            f'font-size="14" '
            f'class="primary">{language}</text>'
        )

        svg.append(
            f'<rect x="160" y="{y - 13}" '
            f'width="{max_bar_width}" height="16" '
            f'rx="8" class="bar-background"/>'
        )

        svg.append(
            f'<rect x="160" y="{y - 13}" '
            f'width="{bar_width:.2f}" height="16" '
            f'rx="8" class="bar"/>'
        )

        svg.append(
            f'<text x="{width - 40}" y="{y}" '
            f'text-anchor="end" '
            f'font-family="Arial, Helvetica, sans-serif" '
            f'font-size="14" '
            f'class="secondary">{percentage:.2f}%</text>'
        )

        y += row_height

    svg.append("</svg>")

    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(svg))

def main():
    print(f"Collecting GitHub statistics for {USERNAME}...\n")

    repositories = get_repositories()

    print(f"Found {len(repositories)} repositories.\n")

    statistics = calculate_statistics(repositories)

    language_percentages = calculate_language_percentages(
        statistics["languages"]
    )

    generate_stats_svg(statistics)

    print("\n" + "=" * 50)
    print("GitHub Statistics")
    print("=" * 50)

    print(f"Commits:       {statistics['commits']:,}")
    print(f"Lines added:   {statistics['added']:,}")
    print(f"Lines deleted: {statistics['deleted']:,}")
    print(f"Net lines:     {statistics['net']:,}")

    print("\nLanguages:")

    for language, percentage in sorted(
        language_percentages.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        if percentage < 0.01:
            continue
        
        print(f"  {language:<20} {percentage:6.2f}%")

    print("=" * 50)


if __name__ == "__main__":
    main()
