"""项目分析和分类模块"""
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np


def analyze_trending(repositories):
    """
    分析趋势项目：
    - all_time_stars: 历史高星
    - fast_growing: 近期快速增长（按 updated_at 和 stars 比率分析）
    - trending: 综合评分
    """
    now = datetime.utcnow()

    for repo in repositories:
        repo["_score"] = repo.get("stargazers_count", 0)
        repo["_growth_rate"] = 0

        created_at = repo.get("created_at", "")
        updated_at = repo.get("updated_at", "")

        # 计算项目年龄（天）
        try:
            created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ") if created_at else now
            age_days = max((now - created).days, 1)
        except Exception:
            age_days = 365

        stars = repo.get("stargazers_count", 0)
        forks = repo.get("forks_count", 0)

        # 综合评分：考虑 stars、forks、年龄、是否有描述、open issues
        repo["_composite_score"] = (
            stars * 0.5 +
            forks * 0.15 +
            (stars / age_days) * 100 * 0.2 +
            (100 if repo.get("description") else 0) * 0.1 +
            (50 if repo.get("language") else 0) * 0.05
        )

        # 增长速度指标（stars/年龄）
        repo["_stars_per_day"] = stars / age_days

        # 近30天是否有活跃更新
        try:
            updated = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%SZ") if updated_at else now
            recent_days = (now - updated).days
            repo["_recently_updated"] = recent_days < 30
        except Exception:
            repo["_recently_updated"] = False

        # 近期增长潜力（开放 issue 多且活跃）
        open_issues = repo.get("open_issues_count", 0)
        repo["_activity_potential"] = open_issues if repo["_recently_updated"] else 0

    # 排序
    all_time_stars = sorted(repositories, key=lambda r: r.get("stargazers_count", 0), reverse=True)

    fast_growing = sorted(
        [r for r in repositories if r.get("_stars_per_day", 0) > 5],
        key=lambda r: r.get("_stars_per_day", 0),
        reverse=True
    )

    trending = sorted(repositories, key=lambda r: r.get("_composite_score", 0), reverse=True)

    return {
        "all_time_stars": all_time_stars[:500],
        "fast_growing": fast_growing[:500],
        "trending": trending[:500]
    }


def categorize_repositories(repositories):
    """按编程语言分类"""
    categories = defaultdict(list)
    for repo in repositories:
        lang = repo.get("language") or "Other"
        categories[lang].append(repo)

    for lang in categories:
        categories[lang] = sorted(
            categories[lang],
            key=lambda r: r.get("stargazers_count", 0),
            reverse=True
        )

    return dict(categories)


def get_stats_summary(repositories):
    """生成统计摘要"""
    total_stars = sum(r.get("stargazers_count", 0) for r in repositories)
    total_forks = sum(r.get("forks_count", 0) for r in repositories)
    total_open_issues = sum(r.get("open_issues_count", 0) for r in repositories)
    languages = set(r.get("language") for r in repositories if r.get("language"))

    return {
        "total_repos": len(repositories),
        "total_stars": total_stars,
        "total_forks": total_forks,
        "total_open_issues": total_open_issues,
        "languages_count": len(languages),
        "languages": sorted(languages)[:20]
    }
