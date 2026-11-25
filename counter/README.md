# 博客访问计数

主页和每篇文章分别累计。相同浏览器在同一页从最近一次计入起的 30 分钟内重复打开，只计一次。不同浏览器、无痕窗口和清理站点数据后的访问可能分开计数。浏览器使用每页独立的随机标识，服务端只留该标识的哈希和去重时间，SQLite 保存累计数。服务端按同一事务完成去重和加一，过期去重记录在之后写入时清理。浏览器无法保存标识时，只查询读数。累计数从正式启用时开始。

## 本机预览

用 Python 3.10 或更新版本，在仓库根目录运行以下命令。数据库参数指向仓库之外的临时文件。

```powershell
py -3.12 -B -m counter.preview --database "$env:TEMP/haifeng-blog-preview.sqlite3"
```

打开 [本机博客预览](http://127.0.0.1:8765/)。测试运行 `py -3.12 -B -m unittest discover -s counter`。

新文章沿用其他文章的 `views.js` 脚本和计数标记，将 `data-view-page` 设为 `posts/文章目录名`。服务会核对对应的 `docs/posts/文章目录名/index.html`，因此上线时把待发布版本的 `docs` 同步给计数后端。

## 上线

GitHub Pages 发布 `docs/`。计数 API 单独运行，用持久化目录保存数据库，并在 HTTPS 反向代理只开放 `/api/blog-views`。用生产 WSGI 服务器启动 `counter.server:create_app()`。`deploy/` 提供 systemd 服务及 nginx 配置，服务将 Gunicorn 绑定到 `127.0.0.1:8791`。设置 `BLOG_VIEWS_DATABASE` 为服务账户可写目录中的数据库文件，`BLOG_VIEWS_SITE_ROOT` 为发布版本的 `docs` 绝对路径。允许的前端来源默认为 `https://lehaifeng000.github.io`。

反代对该接口限制频率和请求大小，关闭访问日志，保留 `Origin` 并剥离转发给计数服务的访客 IP、Cookie 和 Referer。接入后，用线上博客来源核对预检、GET 和重复 POST。确认通过后，将 HTTPS 地址填入 `docs/assets/views.js` 的 `liveEndpoint`，再发布博客。只读查询用 `GET /api/blog-views?page=home`，其他页面的键例如 `posts/numpy-bp`。
