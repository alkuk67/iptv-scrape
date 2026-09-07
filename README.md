# IPTV 酒店源爬虫

只抓取存活天数 > 0 的酒店源（过滤掉新上线），每个源最多取5页频道，全程限速避免被封禁。

## 限速策略

- 初始等待 3s
- 每页之间等待 5-10s 随机
- 每源之间等待 5-10s 随机
- 每抓 10 页额外等待 30-60s
- Playwright 超时 90s（遇错继续下一页，不中断）

## 使用

### 本地运行

``bash
pip install -r requirements.txt
playwright install chromium
python src/scrape_multicast.py
`

### Docker 运行

``bash
# 构建镜像
docker build -t iptv-scrape .

# 运行一次
docker run --rm -v \D:\yuanl\Documents\GitHub\projects\iptv-scrape/data:/app/data iptv-scrape

# 定期运行（使用 docker-compose）
docker-compose up -d

# ARM 设备（玩客云等）
# 修改 docker-compose.yml 中的 platform: linux/arm64
docker-compose -f docker-compose.yml up -d
`

输出文件：
- data/multicast_sources_filtered.json - 过滤后的酒店源列表
- data/channels_all.json - 原始频道数据
- data/channels_alive.json - 探针验证结果
- data/scraper.log - 运行日志

## 部署

### 方式1：本地 / 常开电脑（最简单）

直接运行即可，适合偶尔手动跑一次。

### 方式2：Docker / 玩客云（推荐）

`ash
# 构建并运行
docker build -t iptv-scrape .
docker run -d --name iptv-scrape -v ./data:/app/data --restart unless-stopped iptv-scrape

# ARM 设备（如玩客云）
# 1. 编辑 docker-compose.yml，取消注释 platform: linux/arm64
# 2. 在设备上执行：
docker-compose up -d

# 查看日志
docker logs -f iptv-scrape
`

### 方式3：VPS

`ash
# Ubuntu/Debian
apt update && apt install python3 python3-pip docker.io docker-compose -y
git clone <repo> && cd iptv-scrape
docker-compose up -d
`

推荐用 crontab 定时运行（不推荐，Docker 更稳定）。

### 方式4：GitHub Actions

在 .github/workflows/scrape.yml：

`yaml
name: IPTV Scrape
on:
  schedule:
    - cron: '0 19 * * *'  # UTC 19:00 = 北京时间 03:00
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
      - run: python src/scrape_multicast.py --skip-probe
      - uses: actions/upload-artifact@v4
        with:
          name: iptv-data
          path: data/
`

注意：GitHub Actions 的 IP 是共享的，可能被目标站拦截。如遇验证码，建议改用 Docker 部署。

## 数据来源

- 源列表: http://www.foodieguide.com/iptvsearch/iptvmulticast.php
- 频道列表: http://www.foodieguide.com/iptvsearch/channellist.html (Playwright)
