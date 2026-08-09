#!/usr/bin/env python3
"""
GitHub Trending Daily Report Generator

Fetches GitHub trending repositories, enriches with API data (README summary,
topics, license, metrics), translates descriptions to Chinese, and generates
an HTML report. Designed to run in GitHub Actions.
"""

import html
import os
import re
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False


GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_API = 'https://api.github.com'


# GitHub Linguist language colors
LANG_COLORS = {
    'Python': '#3572A5', 'JavaScript': '#f1e05a', 'TypeScript': '#3178c6',
    'Java': '#b07219', 'C++': '#f34b7d', 'C': '#555555', 'C#': '#178600',
    'Go': '#00ADD8', 'Rust': '#dea584', 'Ruby': '#701516', 'PHP': '#4F5D95',
    'Swift': '#F05138', 'Kotlin': '#A97BFF', 'Dart': '#00B4AB', 'Shell': '#89e051',
    'HTML': '#e34c26', 'CSS': '#563d7c', 'Vue': '#41b883', 'Roff': '#ecdebe',
    'Lua': '#000080', 'Scala': '#c22d40', 'Elixir': '#6e4a7e', 'Clojure': '#db5855',
    'Haskell': '#5e5086', 'Zig': '#ec915c', 'Nim': '#ffc200', 'Jupyter Notebook': '#DA5B0B',
    'MDX': '#fcb32c', 'Astro': '#ff5a03', 'Svelte': '#ff3e00', 'Solidity': '#AA6746',
    'Objective-C': '#438eff', 'Perl': '#0298c3', 'R': '#198CE7', 'MATLAB': '#e16737',
    'Assembly': '#6E4C13', 'Groovy': '#4298b8', 'Dockerfile': '#384d54',
    'Makefile': '#427819', 'PowerShell': '#012456', 'Julia': '#a270ba',
    'Crystal': '#000100', 'OCaml': '#3be133', 'Erlang': '#B83998',
    'Fortran': '#4d41b1', 'Elm': '#60B5CC', 'F#': '#b845fc',
}


# ─── Translation helpers ───

def is_chinese(text):
    if not text:
        return True
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_chars > 0


def translate_to_chinese(text):
    """Translate text to Chinese. Returns (chinese_text, original_text_or_None)."""
    if not text or is_chinese(text):
        return text, None
    if not HAS_TRANSLATOR:
        return text, None
    try:
        translated = GoogleTranslator(source='auto', target='zh-CN').translate(text)
        if translated and translated != text:
            return translated, text
        return text, None
    except Exception as e:
        print(f'  Translation failed: {e}')
        return text, None


# ─── GitHub API helpers ───

def _gh_headers(accept='application/vnd.github+json'):
    h = {'Accept': accept}
    if GITHUB_TOKEN:
        h['Authorization'] = f'Bearer {GITHUB_TOKEN}'
    return h


def github_api_get(path, raw=False):
    """Make an authenticated GitHub API GET request."""
    url = f'{GITHUB_API}{path}'
    headers = _gh_headers('application/vnd.github.raw' if raw else 'application/vnd.github+json')
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.text if raw else resp.json()
        if resp.status_code == 404:
            return None
        if resp.status_code == 403 and 'rate limit' in resp.text.lower():
            print(f'  Rate limited by GitHub API, skipping enrichment')
            return None
        print(f'  API {path} returned {resp.status_code}')
        return None
    except requests.RequestException as e:
        print(f'  API request failed: {e}')
        return None


def fetch_repo_details(repo_name):
    """Fetch additional repo metadata via GitHub API."""
    data = github_api_get(f'/repos/{repo_name}')
    if not data:
        return {}
    return {
        'topics': data.get('topics', []),
        'license': (data.get('license') or {}).get('spdx_id', ''),
        'homepage': data.get('homepage', ''),
        'open_issues': data.get('open_issues_count', 0),
        'created_at': data.get('created_at', ''),
        'pushed_at': data.get('pushed_at', ''),
        'watchers': data.get('subscribers_count', 0),
        'archived': data.get('archived', False),
    }


def fetch_readme_summary(repo_name, max_chars=400):
    """Fetch README and extract a brief text summary."""
    raw = github_api_get(f'/repos/{repo_name}/readme', raw=True)
    if not raw:
        return ''

    lines = raw.split('\n')
    meaningful = []
    char_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if meaningful and char_count > 50:
                # paragraph break — keep going to fill up to max_chars
                pass
            continue
        # Skip headers, badges, images, HTML, tables, HR
        if stripped.startswith('#'):
            continue
        if stripped.startswith('![') or stripped.startswith('<img') or stripped.startswith('<p '):
            continue
        if stripped.startswith('[!['):
            continue
        if stripped.startswith('|'):
            continue
        if stripped in ('---', '***', '___'):
            continue
        if stripped.startswith('<') and stripped.endswith('>'):
            continue
        # Skip reference-style link definitions: [name]: url
        if re.match(r'^\[[^\]]+\]:\s*https?://', stripped):
            continue
        # Skip ASCII art / box-drawing lines
        if sum(1 for c in stripped if c in '┌┐└┘│─├┤┬┴┼═║╔╗╚╝╠╣╦╩╬') > 3:
            continue
        # Skip license shields / CI badges
        if 'shields.io' in stripped or 'badge' in stripped.lower():
            continue
        # Clean markdown inline formatting and HTML tags
        clean = re.sub(r'!\[.*?\]\(.*?\)', '', stripped)
        clean = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', clean)
        clean = re.sub(r'<[^>]+>', '', clean)  # strip HTML tags
        clean = html.unescape(clean)  # decode HTML entities like &bull; &amp;
        clean = re.sub(r'`([^`]*)`', r'\1', clean)
        clean = re.sub(r'\*\*([^*]*)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]*)\*', r'\1', clean)
        clean = re.sub(r'\[([^\]]*)\]\[[^\]]*\]', r'\1', clean)  # ref-style links
        clean = re.sub(r'^\s*[-•]\s*', '', clean)  # strip leading list markers
        clean = re.sub(r'#{2,}\s*', '', clean)  # strip remaining ## headers
        clean = clean.strip(' >|')
        if len(clean) < 8:
            continue
        meaningful.append(clean)
        char_count += len(clean)
        if char_count >= max_chars:
            break

    summary = ' '.join(meaningful[:4])
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(' ', 1)[0] + '…'
    return summary


# ─── Analysis helpers ───

def format_time_ago(date_str):
    """Format ISO date string as relative Chinese text."""
    if not date_str:
        return ''
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = now - dt
        if diff.days > 30:
            months = diff.days // 30
            return f'{months}个月前'
        if diff.days > 0:
            return f'{diff.days}天前'
        hours = diff.seconds // 3600
        if hours > 0:
            return f'{hours}小时前'
        return '刚刚'
    except (ValueError, TypeError):
        return ''


def generate_recommendation(repo):
    """Generate a short recommendation reason based on metrics."""
    reasons = []
    stars = repo.get('total_stars', 0)
    today = repo.get('stars_today', 0)
    forks = repo.get('forks', 0)

    # Star milestones
    if stars >= 100000:
        reasons.append('社区庞大（10万+ Star）')
    elif stars >= 50000:
        reasons.append('高人气项目（5万+ Star）')
    elif stars >= 10000:
        reasons.append('热门项目（1万+ Star）')
    elif stars >= 1000:
        reasons.append('稳步增长中（千级 Star）')

    # Growth velocity
    if today >= 1000:
        reasons.append('今日爆发式增长')
    elif today >= 500:
        reasons.append('今日增长强劲')

    # Project age
    created = repo.get('created_at', '')
    if created:
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            days_old = (datetime.now(timezone.utc) - dt).days
            if days_old < 14:
                reasons.append('全新项目，上线不到两周')
            elif days_old < 30:
                reasons.append('新兴项目，上线不到一个月')
            elif days_old < 90:
                reasons.append('近期新项目')
        except ValueError:
            pass

    # Activity
    pushed = repo.get('pushed_at', '')
    if pushed:
        try:
            dt = datetime.fromisoformat(pushed.replace('Z', '+00:00'))
            days_since = (datetime.now(timezone.utc) - dt).days
            if days_since <= 3:
                reasons.append('活跃维护中')
            elif days_since <= 7:
                reasons.append('本周有更新')
        except ValueError:
            pass

    # Fork engagement
    if forks >= 10000:
        reasons.append('社区贡献活跃')

    if not reasons:
        reasons.append('值得关注的新趋势')

    return '；'.join(reasons)


# ─── Trending page parsing ───

def fetch_trending():
    """Fetch and parse GitHub trending repositories."""
    url = 'https://github.com/trending'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    resp = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            print(f'  Attempt {attempt + 1} failed: {e}')
            if attempt == 2:
                raise
            time.sleep(5)

    soup = BeautifulSoup(resp.text, 'html.parser')
    repos = []

    articles = soup.select('article.Box-row')
    if not articles:
        articles = soup.find_all('article')

    for article in articles:
        repo = parse_article(article)
        if repo and repo.get('repo_name'):
            repos.append(repo)

    return repos


def parse_article(article):
    """Parse a single trending repo article element."""
    h2 = article.find('h2')
    if not h2:
        return None
    a = h2.find('a')
    if not a:
        return None

    href = a.get('href', '').strip()
    repo_name = href.strip('/')
    if not repo_name or '/' not in repo_name:
        return None

    repo_url = f'https://github.com/{repo_name}'
    raw_name = a.get_text(separator=' ', strip=True)
    display_name = re.sub(r'\s+', ' ', raw_name).strip() or repo_name

    p = article.find('p')
    description = p.get_text(strip=True) if p else ''

    lang_el = article.find(attrs={'itemprop': 'programmingLanguage'})
    language = lang_el.get_text(strip=True) if lang_el else ''

    total_stars = 0
    forks = 0
    for link in article.find_all('a'):
        link_href = link.get('href', '')
        link_text = link.get_text(strip=True).replace(',', '').replace(' ', '')
        if '/stargazers' in link_href:
            try:
                total_stars = int(link_text)
            except ValueError:
                pass
        elif '/forks' in link_href:
            try:
                forks = int(link_text)
            except ValueError:
                pass

    stars_today = 0
    for span in article.find_all('span'):
        text = span.get_text(strip=True)
        match = re.search(r'([\d,]+)\s+stars?\s+(today|this week|this month)', text, re.IGNORECASE)
        if match:
            stars_today = int(match.group(1).replace(',', ''))
            break

    return {
        'name': display_name,
        'repo_name': repo_name,
        'url': repo_url,
        'description': description,
        'language': language,
        'total_stars': total_stars,
        'stars_today': stars_today,
        'forks': forks,
    }


# ─── Enrichment ───

def enrich_repos(repos):
    """Fetch additional details and README summary for each repo."""
    total = len(repos)
    for i, repo in enumerate(repos, 1):
        name = repo['repo_name']
        print(f'  [{i}/{total}] Enriching {name}...')

        # Repo metadata
        details = fetch_repo_details(name)
        repo.update(details)

        # README summary
        readme_raw = fetch_readme_summary(name)
        if readme_raw:
            zh_summary, orig_summary = translate_to_chinese(readme_raw)
            repo['readme_zh'] = zh_summary
            repo['readme_orig'] = orig_summary
        else:
            repo['readme_zh'] = ''
            repo['readme_orig'] = None

        # Translate description
        zh_desc, orig_desc = translate_to_chinese(repo['description'])
        repo['zh_description'] = zh_desc
        repo['orig_description'] = orig_desc

        # Recommendation
        repo['recommendation'] = generate_recommendation(repo)

        # Be nice to the API
        time.sleep(0.3)


# ─── HTML generation ───

CSS = """        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, -apple-system, "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f6f8fa; color: #1f2328; line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #6e40c9 0%, #2563eb 100%);
            color: white; padding: 48px 20px 40px; text-align: center;
        }
        .header h1 { font-size: 28px; margin-bottom: 8px; font-weight: 700; }
        .header h1 a { color: white; text-decoration: none; }
        .header .meta { font-size: 14px; opacity: 0.9; }
        .container { max-width: 960px; margin: -20px auto 0; padding: 0 16px 48px; position: relative; }
        .summary {
            background: white; border-radius: 12px; padding: 24px; margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            display: flex; gap: 16px; justify-content: space-around; flex-wrap: wrap;
        }
        .summary-item { text-align: center; min-width: 100px; }
        .summary-item .value { font-size: 28px; font-weight: 700; color: #6e40c9; }
        .summary-item .label { font-size: 12px; color: #848d97; margin-top: 4px; }
        .card {
            background: white; border-radius: 12px; padding: 20px 24px; margin-bottom: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            transition: box-shadow 0.2s ease, transform 0.2s ease;
            border: 1px solid #e9ecef;
        }
        .card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.10); transform: translateY(-2px); }
        .card-top { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
        .rank {
            font-size: 13px; color: #848d97; font-weight: 700;
            background: #f6f8fa; border-radius: 8px; min-width: 28px; height: 28px;
            display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        }
        .rank.top3 { background: linear-gradient(135deg, #6e40c9, #2563eb); color: white; }
        .card-title { font-size: 17px; font-weight: 600; }
        .card-title a { color: #0969da; text-decoration: none; }
        .card-title a:hover { text-decoration: underline; }
        .description { color: #59636e; font-size: 14px; margin-bottom: 8px; padding-left: 40px; }
        .description .original { color: #adbac7; font-size: 13px; font-style: italic; }
        .readme-summary {
            background: #f6f8fa; border-radius: 8px; padding: 10px 14px;
            margin: 6px 0 6px 40px; font-size: 13px; color: #59636e;
            border-left: 3px solid #d0d7de; line-height: 1.7;
        }
        .readme-summary .label { font-weight: 600; color: #656d76; }
        .readme-summary .orig { color: #adbac7; font-size: 12px; font-style: italic; }
        .recommendation {
            margin: 6px 0 8px 40px; font-size: 13px; color: #1a7f37; font-weight: 500;
        }
        .topics { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px 40px; }
        .topic-badge {
            background: #ddf4ff; color: #0969da; padding: 2px 10px;
            border-radius: 20px; font-size: 11px; font-weight: 500;
        }
        .card-footer {
            display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
            font-size: 12px; color: #59636e; padding-left: 40px;
        }
        .lang-badge {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 3px 10px; border-radius: 20px; font-size: 11px;
            font-weight: 500; background: #f6f8fa;
        }
        .lang-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
        .stat { display: inline-flex; align-items: center; gap: 3px; }
        .stat-icon { font-size: 13px; }
        .stars-today { color: #1a7f37; font-weight: 600; }
        .footer-note { text-align: center; color: #848d97; font-size: 12px; margin-top: 32px; }
        .footer-note a { color: #0969da; text-decoration: none; }
        .report-list { list-style: none; }
        .report-item {
            background: white; border-radius: 12px; padding: 16px 24px; margin-bottom: 10px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid #e9ecef;
            transition: box-shadow 0.2s ease, transform 0.2s ease;
        }
        .report-item:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.10); transform: translateY(-2px); }
        .report-item a { color: #0969da; text-decoration: none; font-size: 16px; font-weight: 600; }
        .report-item a:hover { text-decoration: underline; }
        .report-item .date { color: #848d97; font-size: 13px; margin-top: 4px; }
        @media (max-width: 600px) {
            .card-footer { gap: 10px; } .summary { gap: 12px; }
            .summary-item .value { font-size: 22px; }
            .description, .readme-summary, .recommendation, .topics, .card-footer { padding-left: 0; margin-left: 0; }
        }"""


def _esc(text):
    """Minimal HTML escape."""
    if not text:
        return ''
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def generate_card_html(repo, rank):
    """Generate HTML for a single repo card."""
    lang = repo.get('language') or '未指定'
    lang_color = LANG_COLORS.get(repo.get('language'), '#848d97')
    top3_class = ' top3' if rank <= 3 else ''

    # Description
    desc = repo.get('zh_description') or '暂无描述'
    orig = repo.get('orig_description')
    desc_html = f'{_esc(desc)} <span class="original">({_esc(orig)})</span>' if orig else _esc(desc)

    # README summary
    readme_zh = repo.get('readme_zh', '')
    readme_orig = repo.get('readme_orig')
    readme_html = ''
    if readme_zh:
        orig_part = f' <span class="orig">{_esc(readme_orig)}</span>' if readme_orig else ''
        readme_html = f"""            <div class="readme-summary">
                <span class="label">📖 项目简介</span>：{_esc(readme_zh)}{orig_part}
            </div>"""

    # Recommendation
    rec = repo.get('recommendation', '')
    rec_html = f'            <div class="recommendation">💡 推荐理由：{_esc(rec)}</div>' if rec else ''

    # Topics
    topics = repo.get('topics', [])
    topics_html = ''
    if topics:
        badges = ''.join(f'<span class="topic-badge">{_esc(t)}</span>' for t in topics[:8])
        topics_html = f'            <div class="topics">{badges}</div>'

    # Extra metrics
    extra_stats = ''
    issues = repo.get('open_issues', 0)
    if issues:
        extra_stats += f'<span class="stat"><span class="stat-icon">📋</span> {issues} issues</span>'
    pushed_ago = format_time_ago(repo.get('pushed_at', ''))
    if pushed_ago:
        extra_stats += f'<span class="stat"><span class="stat-icon">📅</span> 更新于{pushed_ago}</span>'
    license = repo.get('license', '')
    if license and license != 'NOASSERTION':
        extra_stats += f'<span class="stat"><span class="stat-icon">📄</span> {license}</span>'
    homepage = repo.get('homepage', '')
    if homepage:
        extra_stats += f'<span class="stat"><span class="stat-icon">🏠</span> <a href="{homepage}" style="color:#0969da;text-decoration:none;">主页</a></span>'

    return f"""        <div class="card">
            <div class="card-top">
                <div class="rank{top3_class}">{rank}</div>
                <div class="card-title"><a href="{repo['url']}">{_esc(repo['name'])}</a></div>
            </div>
            <div class="description">
                {desc_html}
            </div>
{readme_html}
{rec_html}
{topics_html}
            <div class="card-footer">
                <span class="lang-badge"><span class="lang-dot" style="background:{lang_color}"></span>{lang}</span>
                <span class="stat"><span class="stat-icon">⭐</span> {repo['total_stars']:,}</span>
                <span class="stat stars-today"><span class="stat-icon">📈</span> +{repo['stars_today']:,} 今日</span>
                <span class="stat"><span class="stat-icon">🍴</span> {repo['forks']:,}</span>
                {extra_stats}
            </div>
        </div>"""


def generate_report_html(repos, date_str):
    """Generate the full HTML report page."""
    repos_sorted = sorted(repos, key=lambda r: r['stars_today'], reverse=True)
    total_stars_today = sum(r['stars_today'] for r in repos_sorted)
    languages = set(r['language'] for r in repos_sorted if r['language'])

    cards = '\n'.join(
        generate_card_html(repo, i) for i, repo in enumerate(repos_sorted, 1)
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub 趋势项目日报 - {date_str}</title>
    <style>
{CSS}
    </style>
</head>
<body>
    <div class="header">
        <h1><a href="../index.html">🔥 GitHub 趋势项目日报</a></h1>
        <div class="meta">{date_str} · 共 {len(repos_sorted)} 个项目</div>
    </div>
    <div class="container">
        <div class="summary">
            <div class="summary-item">
                <div class="value">{len(repos_sorted)}</div>
                <div class="label">趋势项目</div>
            </div>
            <div class="summary-item">
                <div class="value">{len(languages)}</div>
                <div class="label">编程语言</div>
            </div>
            <div class="summary-item">
                <div class="value">{total_stars_today:,}</div>
                <div class="label">今日新增 Star 总数</div>
            </div>
        </div>

{cards}

        <div class="footer-note">
            数据来源：<a href="https://github.com/trending">GitHub Trending</a> · 每日 09:00（北京时间）自动生成
        </div>
    </div>
</body>
</html>"""


def generate_index_html(report_files):
    """Generate the index page listing all available reports."""
    items = []
    for filename in report_files:
        match = re.match(r'github-trending-(\d{4}-\d{2}-\d{2})\.html', filename)
        if not match:
            continue
        date_str = match.group(1)
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            display_date = f'{date_str}（{weekdays[dt.weekday()]}）'
        except ValueError:
            display_date = date_str

        items.append(f"""        <div class="report-item">
            <a href="reports/{filename}">📊 {date_str} GitHub 趋势日报</a>
            <div class="date">{display_date}</div>
        </div>""")

    items_html = '\n'.join(items) if items else \
        '        <p style="text-align:center;color:#848d97;padding:40px 0;">暂无报告，请等待首次自动生成。</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub 趋势项目日报</title>
    <style>
{CSS}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 GitHub 趋势项目日报</h1>
        <div class="meta">每日 09:00（北京时间）自动抓取 · 共 {len(items)} 期报告</div>
    </div>
    <div class="container">
        <div class="report-list">
{items_html}
        </div>
        <div class="footer-note">
            数据来源：<a href="https://github.com/trending">GitHub Trending</a> · 由 GitHub Actions 自动生成
        </div>
    </div>
</body>
</html>"""


def main():
    beijing_tz = timezone(timedelta(hours=8))
    now = datetime.now(beijing_tz)
    date_str = now.strftime('%Y-%m-%d')

    print(f'Fetching GitHub Trending for {date_str}...')
    repos = fetch_trending()
    print(f'Found {len(repos)} repos')

    if not repos:
        print('WARNING: No repos found! Generating empty report.')

    print('Enriching repos with API data...')
    enrich_repos(repos)

    print('Generating report HTML...')
    html = generate_report_html(repos, date_str)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    docs_dir = os.path.join(repo_root, 'docs')
    reports_dir = os.path.join(docs_dir, 'reports')
    os.makedirs(reports_dir, exist_ok=True)

    report_filename = f'github-trending-{date_str}.html'
    report_path = os.path.join(reports_dir, report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Report saved: {report_path}')

    existing_reports = sorted(
        [f for f in os.listdir(reports_dir)
         if f.endswith('.html') and f.startswith('github-trending-')],
        reverse=True
    )
    index_html = generate_index_html(existing_reports)
    index_path = os.path.join(docs_dir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(index_html)
    print(f'Index updated: {index_path}')


if __name__ == '__main__':
    main()
