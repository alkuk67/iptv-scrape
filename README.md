# IPTV 酒店源爬虫

只抓取存活天数 > 0 的酒店源（过滤掉新上线），每个源最多取5页频道，全程限速避免被封禁。

## 限速策略

- 初始等待 3s
- 每页之间等待 6s
- 每个源之间等待 8s
- Playwright 超时 90s（遇错继续下一页，不中断）

## 使用

``bash
pip install -r requirements.txt
playwright install chromium
python src/scrape_multicast.py
``

输出文件：
- `data/multicast_sources_filtered.json` - 过滤后的酒店源列表
- `data/channels_all.json` - 所有频道数据

## 部署

### 方式1：本地 / 常开电脑（最简单）

直接运行即可，适合偶尔手动跑一次。

### 方式2：VPS（推荐长期运行）

``bash
# Ubuntu 22.04+ / Debian 12+
apt update && apt install -y python3 python3-pip python3-venv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
python src/scrape_multicast.py
``

推荐用 `crontab -e` 添加定时任务（每天凌晨3点）：

``
0 3 * * * cd /path/to/iptv-scrape && source venv/bin/activate && python src/scrape_multicast.py >> data/scraper.log 2>&1
``

### 方式3：GitHub Actions（免费定时运行）

在 `.github/workflows/scrape.yml`：

``yaml
name: IPTV Scrape
on:
  schedule:
    - cron: '0 19 * * *'  # UTC 19:00 = 北京时间凌晨3点
  workflow_dispatch:
jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: playwright install --with-deps chromium
      - run: python src/scrape_multicast.py
      - uses: actions/upload-artifact@v4
        with:
          name: iptv-data
          path: data/
``

注意：GitHub Actions 的 IP 是共享的，目标站可能对 GitHub IP 段有更严格的限速。
如果被拦截，优先用 VPS。

