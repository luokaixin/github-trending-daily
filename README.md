# GitHub 趋势项目日报

每日自动抓取 GitHub Trending 项目，将描述翻译为中文，生成 HTML 报告并通过 GitHub Pages 提供 Web 访问。

## 功能

- 每日 09:00（北京时间）自动运行（GitHub Actions cron）
- 抓取 GitHub Trending 页面全部语言趋势项目
- 使用 Google Translate 将非中文描述翻译为中文
- 生成卡片式 HTML 报告（按今日新增 Star 降序排列）
- 通过 GitHub Pages 提供网页访问，首页列出所有历史报告

## 项目结构

```
├── .github/workflows/trending.yml    # GitHub Actions 工作流
├── scripts/generate_trending_report.py  # 抓取与报告生成脚本
├── docs/                             # GitHub Pages 根目录
│   ├── index.html                    # 报告列表首页
│   └── reports/                      # 每日报告 HTML 文件
├── requirements.txt                  # Python 依赖
└── README.md
```

## 手动触发

在仓库的 **Actions** 页面选择 "GitHub Trending Daily Report"，点击 **Run workflow** 即可手动触发。
