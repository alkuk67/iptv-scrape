#!/usr/bin/env python3
"""
Scrape surviving hotel IPTV multicast sources from foodieguide.com.
Only fetches sources with survival_days > 0 (hotels, not new).
Fetches up to MAX_PAGES_PER_SOURCE pages per source with randomized delays.
"""

import json
import os
import re
import random
import time
import sys
import html as htmlmod
from datetime import datetime
from scrapling import StealthyFetcher
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.error
import logging

# -- Config --
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_SOURCES = os.path.join(BASE_DIR, "data", "multicast_sources_filtered.json")
OUTPUT_CHANNELS = os.path.join(BASE_DIR, "data", "channels_all.json")
MAX_PAGES_PER_SOURCE = 5
MIN_DELAY_PAGE = 5.0
MAX_DELAY_PAGE = 10.0
EXTRA_DELAY_EVERY_N_PAGES = 10
MIN_EXTRA_DELAY = 30.0
MAX_EXTRA_DELAY = 60.0
MAX_SESSION_SECS = 600
DELAY_INIT = 3.0
PLAYWRIGHT_TIMEOUT = 90000

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

LOC_PAT = r'(\u5c71\u4e1c\u7701|\u4e0a\u6d77\u5e02|\u5b89\u5fbd\u7701|\u56db\u5ddd\u7701|\u6d59\u6c5f\u7701|\u6c5f\u82cf\u7701|\u5e7f\u4e1c\u7701|\u91cd\u5e86\u5e02|\u5c71\u897f\u7701|\u6e56\u5317\u7701|\u6e56\u5357\u7701|\u798f\u5efa\u7701|\u6c5f\u897f\u7701|\u6cb3\u5357\u7701|\u6cb3\u5317\u7701|\u8fbd\u5b81\u7701|\u5409\u6797\u7701|\u9ed1\u9f99\u6c5f\u7701|\u4e91\u5357\u7701|\u8d35\u5dde\u7701|\u9655\u897f\u7701|\u7518\u8083\u7701|\u9752\u6d77\u7701|\u53f0\u6e7e|\u5185\u8499\u53e4|\u5e7f\u897f|\u897f\u85cf|\u5b81\u590f|\u65b0\u7586|\u5317\u4eac|\u5929\u6d25|\u9999\u6e2f)'
OP_PAT = r'(\u7535\u4fe1|\u8054\u901a|\u79fb\u52a8)'
NEW_LABEL = "\u65b0\u4e0a\u7ebf"
ALIVE = "\u5b58\u6d3b"
DAYS = "\u5929"
# Probe config
PROBE_WORKERS = 4          # concurrent HTTP probes
PROBE_TIMEOUT = 5          # seconds per URL
PROBE_DELAY = 0.3          # delay between probes
OUTPUT_ALIVE = os.path.join(BASE_DIR, "data", "channels_alive.json")
LOG_FILE = os.path.join(BASE_DIR, "data", "scraper.log")


def setup_logger(log_file):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logger = logging.getLogger("scraper")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8", mode="a")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(ch)
    return logger



def rand_page_delay():
    return random.uniform(MIN_DELAY_PAGE, MAX_DELAY_PAGE)


def fetch_multicast_sources():
    """Fetch multicast sources with retry and verification handling."""
    url = "http://www.foodieguide.com/iptvsearch/iptvmulticast.php"
    last_body = None
    last_status = None
    
    for attempt in range(3):
        try:
            f = StealthyFetcher()
            r = f.fetch(url)
            last_body = r.body
            last_status = r.status
            
            # Check if we got blocked/verified
            body_text = r.body.decode("utf-8", errors="replace")
            if "verify" in r.url.lower() or "tonkiang" in r.url.lower():
                print(f"  [WARNING] Redirected to verification page (attempt {attempt+1})")
                if attempt < 2:
                    time.sleep(10)
                    continue
            
            # Check if content looks like actual source list
            if len(body_text) > 5000 and "result" in body_text:
                return body_text
            
            print(f"  [WARNING] Unexpected response: status={r.status}, len={len(body_text)}")
            if attempt < 2:
                time.sleep(5)
                
        except Exception as e:
            print(f"  [WARNING] Fetch attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(8)
    
    # Return whatever we got
    return last_body.decode("utf-8", errors="replace") if last_body else ""


def parse_multicast_sources(html):
    sources = []
    parts = html.split('<div class="result">')
    for part in parts[1:]:
        item = {}
        m = re.search(r'href="channellist\.html\?ip=([^&]+)', part)
        if not m:
            continue
        item["ip"] = htmlmod.unescape(m.group(1))
        t = re.search(r'tk=([a-f0-9]+)', part)
        item["tk"] = t.group(1) if t else ""
        c = re.search(r'<b>(\d+)</b>', part)
        item["channel_count"] = int(c.group(1)) if c else 0
        d = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', part)
        if d:
            item["online_datetime"] = d.group(1)
            item["online_date"] = d.group(1).split()[0]
        sv = re.search(r'color:limegreen[^>]*>(.*?)</div>', part, re.DOTALL)
        if sv:
            st = sv.group(1)
            if NEW_LABEL in st:
                item["survival_status"] = NEW_LABEL
                item["survival_days"] = 0
            else:
                dm = re.search(r'<b>\s*(\d+)\s*</b>', st)
                if dm:
                    item["survival_days"] = int(dm.group(1))
                    item["survival_status"] = ALIVE + str(dm.group(1)) + DAYS
        im = re.search(r'<i>(.*?)</i>', part, re.DOTALL)
        if im:
            info = im.group(1)
            om = re.search(OP_PAT, info)
            if om:
                item["operator"] = om.group(1)
            lm = re.search(LOC_PAT, info)
            if lm:
                item["location"] = lm.group(1)
        if item.get("ip"):
            sources.append(item)
    return sources


def filter_hotel_sources(sources):
    return [s for s in sources if s.get("survival_days", 0) > 0]




def probe_url(url, timeout=5):
    """Check if a stream URL responds. Returns 'alive' or 'dead'."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", BROWSER_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "alive" if resp.status < 400 else "dead"
    except Exception:
        pass
    # Fallback: GET first few bytes
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", BROWSER_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            _ = resp.read(512)
            return "alive" if resp.status < 400 else "dead"
    except Exception:
        return "dead"


def probe_channels(channels):
    """Probe all channel URLs with limited concurrency."""
    import time as _time
    alive_count = 0
    dead_count = 0
    results = []

    def _probe_one(item):
        result = dict(item)
        result["alive"] = probe_url(result.get("stream_url", ""), timeout=PROBE_TIMEOUT)
        return result

    total = len(channels)
    print(f"      Probing {total} URLs (workers={PROBE_WORKERS})...")
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as executor:
        futures = {executor.submit(_probe_one, ch): i for i, ch in enumerate(channels)}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if result["alive"] == "alive":
                alive_count += 1
            else:
                dead_count += 1
            if (alive_count + dead_count) % 50 == 0 or (alive_count + dead_count) == total:
                print(f"      {alive_count + dead_count}/{total} done ({alive_count} alive, {dead_count} dead)")
            _time.sleep(PROBE_DELAY)

    # Restore original order
    # Reorder results by original channel index
    indexed = []
    for future in futures:
        result = future.result()
        orig_idx = futures[future]
        indexed.append((orig_idx, result))
    indexed.sort(key=lambda x: x[0])
    ordered = [r for _, r in indexed]

    print(f"      Done: {alive_count} alive, {dead_count} dead out of {total}")
    return ordered

def fetch_channels_playwright(ip, tk):
    sys.stdout.reconfigure(encoding="utf-8")
    all_urls, all_names = [], []
    page_count = 0
    session_start = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=BROWSER_UA,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            reduced_motion="reduce",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = ctx.new_page()
        for p in range(1, MAX_PAGES_PER_SOURCE + 1):
            if time.time() - session_start > MAX_SESSION_SECS:
                print(f"      Session limit ({MAX_SESSION_SECS}s) reached after {page_count} pages, stopping")
                break
            captured = {}

            def make_h(d):
                def fn(resp):
                    if "getall" in resp.url:
                        d["text"] = resp.text()
                        d["status"] = resp.status
                return fn

            h = make_h(captured)
            page.on("response", h)
            url = f"http://www.foodieguide.com/iptvsearch/channellist.html?ip={ip}&tk={tk}&p={p}"
            try:
                page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT)
                time.sleep(2)
            except Exception as e:
                print(f"      Page {p} error: {e}")
                if h:
                    page.remove_listener("response", h)
                time.sleep(rand_page_delay())
                continue
            if h:
                page.remove_listener("response", h)
            text = captured.get("text", "")
            if len(text) > 500:
                urls = [u.strip() for u in re.findall(r"'(https?://[^\s'<>]+)'", text)]
                names = [n.strip() for n in re.findall(r'class="tip"[^>]*>([^<]+)<', text) if n.strip()]
                print(f"      p={p}: got {len(urls)} channels")
                all_urls.extend(urls)
                all_names.extend(names)
                page_count += 1
            elif p == 1:
                pass
            else:
                print(f"      p={p}: empty, stopping")
                break
            pdelay = rand_page_delay()
            if page_count % EXTRA_DELAY_EVERY_N_PAGES == 0:
                extra = random.uniform(MIN_EXTRA_DELAY, MAX_EXTRA_DELAY)
                print(f"      -- extra pause {extra:.0f}s (every {EXTRA_DELAY_EVERY_N_PAGES} pages) --")
                pdelay += extra
            time.sleep(pdelay)
        browser.close()

    channels = []
    ml = max(len(all_urls), len(all_names))
    for i in range(ml):
        item = {}
        if i < len(all_names):
            item["channel_name"] = all_names[i]
        if i < len(all_urls):
            item["stream_url"] = all_urls[i]
        if item.get("channel_name") or item.get("stream_url"):
            channels.append(item)
    return channels


def main(skip_probe=False):
    logger = setup_logger(LOG_FILE)
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 60)
    print(f"IPTV Hotel Source Scraper - {now_str}")
    print("=" * 60)
    print("\n[1/4] Fetching multicast source list...")
    time.sleep(DELAY_INIT)
    html = fetch_multicast_sources()
    all_sources = parse_multicast_sources(html)
    logger.info("  Total sources found: %d", len(all_sources))
    hotel_sources = filter_hotel_sources(all_sources)
    logger.info("  Hotel sources (survival_days > 0): %d", len(hotel_sources))
    if not hotel_sources:
        logger.info("  No hotel sources found. Exiting.")
        return
    os.makedirs(os.path.dirname(OUTPUT_SOURCES), exist_ok=True)
    with open(OUTPUT_SOURCES, "w", encoding="utf-8") as f:
        json.dump(hotel_sources, f, ensure_ascii=False, indent=2)
    logger.info("  Saved to %s", OUTPUT_SOURCES)
    for s in hotel_sources:
        print(f"    {s['ip']} | {s.get('channel_count',0)}ch | {s.get('operator','')} | {s.get('location','')} | {s.get('survival_status','')}")
    print(f"\n[2/4] Fetching channel lists (max {MAX_PAGES_PER_SOURCE} pages/source, random {MIN_DELAY_PAGE}-{MAX_DELAY_PAGE}s delay)...")
    all_results = []
    total_channels = 0
    for i, src in enumerate(hotel_sources):
        logger.info("[%d/%d] %s (c=%d, %s)...", i+1, len(hotel_sources), src["ip"], src.get("channel_count", 0), src.get("survival_status", ""))
        channels = fetch_channels_playwright(src["ip"], src["tk"])
        logger.info("      -> %d channels fetched", len(channels))
        for ch in channels:
            ch["ip"] = src["ip"]
            ch["operator"] = src.get("operator", "")
            ch["location"] = src.get("location", "")
            ch["online_date"] = src.get("online_date", "")
            ch["survival_days"] = src.get("survival_days", 0)
        all_results.extend(channels)
        total_channels += len(channels)
        if i < len(hotel_sources) - 1:
            rd = random.uniform(5.0, 10.0)
            logger.info("      -> waiting %.1fs before next source...", rd)
            time.sleep(rd)
    logger.info("Saving raw results...")
    os.makedirs(os.path.dirname(OUTPUT_CHANNELS), exist_ok=True)
    with open(OUTPUT_CHANNELS, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    logger.info("  Total: %d channels from %d sources", total_channels, len(hotel_sources))
    logger.info("  Saved to %s", OUTPUT_CHANNELS)

    if skip_probe:
        logger.info("Skipping probe (CI mode)")
        alive_results = all_results
    else:
        logger.info("Probing channel URLs...")
        alive_results = probe_channels(all_results)
        os.makedirs(os.path.dirname(OUTPUT_ALIVE), exist_ok=True)
        with open(OUTPUT_ALIVE, "w", encoding="utf-8") as f:
            json.dump(alive_results, f, ensure_ascii=False, indent=2)
        alive_count = sum(1 for c in alive_results if c.get("alive") == "alive")
        logger.info("  Saved to %s (%d alive, %d dead)", OUTPUT_ALIVE, alive_count, len(alive_results) - alive_count)

    print("\nPreview (first 5 channels):")
    for c in alive_results[:5]:
        status = c.get("alive", "?")
        print(f"  [{status}] {c.get('channel_name','N/A')}: {c.get('stream_url','N/A')}")
    print("\nDone.")


if __name__ == "__main__":
    skip_probe = "--skip-probe" in sys.argv
    main(skip_probe=skip_probe)
