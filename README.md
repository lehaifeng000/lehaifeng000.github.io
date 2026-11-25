# lehaifeng000.github.io
theme: jekyll-theme-minimal
blog

[博客访问计数和评论](counter/README.md)

## 搜索收录

新增或修改文章后，在仓库根目录运行 `python -B tools/sync_search.py`。脚本从首页已列出的文章生成 `sitemap.xml`、`robots.txt`、规范网址和结构化数据。`python -B tools/sync_search.py --check` 可以检查这些文件是否已同步。

发布后把 `sitemap.xml` 提交到 Google Search Console 和 Bing Webmaster Tools。GitHub Pages 用现有网址的 URL 前缀资源，验证文件放在发布目录 `docs/` 中。
