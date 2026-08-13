import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass
from pathlib import Path
import os

# ====================== 全局配置 ======================
SOURCE_LIST_PATH = Path("sources.list")
OUTPUT_FILE = Path("sou.txt")
TIMEOUT_HTTP = 10
FFMPEG_TIMEOUT = 12
MIN_HEIGHT = 720
MAX_WORKERS = 10

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/plain,application/x-mpegurl,application/vnd.apple.mpegurl,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive"
}

CCTV_NUM_RANGE = range(1, 18)
CCTV_VALID_NUMBERS = set(str(i) for i in CCTV_NUM_RANGE)

CCTV_GENERATE_TEMPLATES = [
    ("http://127.0.0.1/live/cctv{n}.m3u8", "CCTV{n}"),
    ("http://127.0.0.1/live/cctv{n}hd.m3u8", "CCTV{n} HD"),
    ("http://127.0.0.1/tsfile/live/000{n:02d}_1.m3u8", "CCTV{n}"),
    ("http://127.0.0.1/hls/{n}/index.m3u8", "CCTV{n}")
]

# ====================== 正则规则 ======================
RULE_CCTV = re.compile(r"CCTV-?\s*(?:([1-9]|1[0-7])\+?)", re.IGNORECASE)
RULE_MOVIE = re.compile(r"影")
RULE_HENAN = re.compile(r"河南")
RULE_WEISHI = re.compile(r"卫视")
LOW_CCTV_FILTER = re.compile(r"CCTV-?\s*(\d{1,2})\s*-\s*CCTV-?\s*(\d{1,2})", re.IGNORECASE)
CCTV_NUM_EXTRACT = re.compile(r"CCTV-?\s*((?:[1-9]|1[0-7])(?:\+)?)", re.IGNORECASE)
REG_CCTV_STD = re.compile(r"CCTV-?\s*((?:[1-9]|1[0-7])\+?).*?(体育|高清|HD|-体育)", re.IGNORECASE)
REG_SD_FILTER = re.compile(r"标清|SD", re.IGNORECASE)
REG_PROXY_IP = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
REG_IP_PORT = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)")

FORMAT1_PATTERN = re.compile(r"/live/cctv([1-9]|1[0-7])(hd)?\.m3u8", re.IGNORECASE)
FORMAT2_PATTERN = re.compile(r"/tsfile/live/(000|10)(0[1-9]|1[0-7])_1\.m3u8", re.IGNORECASE)
FORMAT3_PATTERN = re.compile(r"/hls/(30)?([1-9]|1[0-7])/index\.m3u8", re.IGNORECASE)
FORMAT4_PATTERN = re.compile(r"cctv([1-9]|1[0-7])hd\.m3u8", re.IGNORECASE)

CCTV_URL_PATTERNS = [
    r"/live/cctv(?:[1-9]|1[0-7])(hd)?\.m3u8(\?.*)?",
    r"/tsfile/live/000(?:0[1-9]|1[0-7])_1\.m3u8(\?.*)?",
    r"/tsfile/live/10(?:0[1-9]|1[0-7])_1\.m3u8(\?.*)?",
    r"/hls/(?:[1-9]|1[0-7])/index\.m3u8(\?.*)?",
    r"/hls/30(?:0[1-9]|1[0-7])/index\.m3u8(\?.*)?",
    r"cctv(?:[1-9]|1[0-7])hd\.m3u8(\?.*)?"
]

REGEX_CCTV_PREFIX = re.compile(r"CCTV-?", re.IGNORECASE)
REGEX_CCTV_NUM = re.compile(r"CCTV-?\s*((?:[1-9]|1[0-7]))", re.IGNORECASE)

# OK影视5分类顺序
GROUP_ORDER = [
    "央视频道,#genre#",
    "电影频道,#genre#",
    "卫视频道,#genre#",
    "河南频道,#genre#",
    "其他频道,#genre#"
]

@dataclass
class ChannelItem:
    extinf: str
    url: str
    name: str
    cctv_digit: Optional[str] = None

# 检测ffmpeg是否可用
def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
        return True
    except Exception:
        return False

def generate_cctv_probe_channels() -> List[ChannelItem]:
    probe_list = []
    for url_tpl, name_tpl in CCTV_GENERATE_TEMPLATES:
        for num in CCTV_NUM_RANGE:
            url = url_tpl.format(n=num)
            ch_name = name_tpl.format(n=num)
            probe_list.append(ChannelItem(f'#EXTINF:-1,{ch_name}', url, ch_name, str(num)))
    print(f"✅ 自动生成探测频道数量：{len(probe_list)}")
    return probe_list

def load_sources() -> List[str]:
    if not SOURCE_LIST_PATH.exists():
        print(f"❌ 错误：{SOURCE_LIST_PATH.name} 文件不存在，请创建并填入源地址！")
        raise SystemExit(1)
    try:
        with open(SOURCE_LIST_PATH, "r", encoding="utf-8") as f:
            lines = [i.strip() for i in f.readlines() if i.strip() and not i.startswith("#")]
        return lines
    except IOError as e:
        print(f"❌ 读取sources.list失败：{str(e)}")
        raise SystemExit(1)

def download_m3u(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=TIMEOUT_HTTP, allow_redirects=True)
        resp.raise_for_status()
        html_signatures = ["<html", "<!DOCTYPE html", "<head", "<body"]
        raw = resp.text.lstrip('\ufeff').strip()
        lower_raw = raw.lower()
        for sig in html_signatures:
            if sig in lower_raw:
                print(f"[拦截HTML] {url} 返回网页，非直播源")
                return None
        return raw
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None

def is_standard_m3u(text: str) -> bool:
    clean = text.strip().lower()
    return clean.startswith("#extm3u") or "#extinf" in clean

def parse_m3u(raw_text: str) -> List[ChannelItem]:
    items = []
    lines = raw_text.splitlines()
    extinf_cache = ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#extm3u") or (line.startswith("#") and not line.startswith("#EXTINF:")):
            continue
        if line.startswith("#EXTINF:"):
            extinf_cache = line
        elif line.startswith("http") and extinf_cache:
            name_match = re.search(r',([^,]+)$', extinf_cache)
            name = name_match.group(1).strip() if name_match else "未知频道"
            digit_match = REGEX_CCTV_NUM.search(name)
            digit = digit_match.group(1) if digit_match else None
            items.append(ChannelItem(extinf_cache, line, name, digit))
            extinf_cache = ""
    return items

def parse_txt_source(raw_text: str) -> List[ChannelItem]:
    items = []
    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        name, url = line.split(",", maxsplit=1)
        name = name.strip()
        url = url.strip()
        if not url.startswith("http"):
            continue
        digit_match = REGEX_CCTV_NUM.search(name)
        digit = digit_match.group(1) if digit_match else None
        items.append(ChannelItem(f'#EXTINF:-1,{name}', url, name, digit))
    return items

def download_and_parse(url: str) -> List[ChannelItem]:
    raw = download_m3u(url)
    if not raw:
        return []
    if is_standard_m3u(raw):
        return parse_m3u(raw)
    else:
        return parse_txt_source(raw)

def check_stream_valid(url: str) -> Tuple[bool, Optional[int]]:
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-rtbufsize", "1M", "-i", url, "-t", "2", "-f", "null", "-"]
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        _, stderr = proc.communicate(timeout=FFMPEG_TIMEOUT)
        err_lower = stderr.lower()
        invalid_words = ["no server configured", "not available in your area", "403 forbidden", "404 not found", "connection refused", "unable to open resource"]
        for kw in invalid_words:
            if kw in err_lower:
                print(f"[源限制] {url} : {kw}")
                return False, None
        res_match = re.search(r"(\d+)x(\d+)", stderr)
        if res_match:
            height = int(res_match.group(2))
            return True, height
        return False, None
    except subprocess.TimeoutExpired:
        if proc: proc.kill()
        print(f"[测速超时] {url}")
        return False, None
    except Exception as e:
        if proc:
            try: proc.kill()
            except: pass
        print(f"[测速异常] {url} : {str(e)}")
        return False, None

def classify_channel(item: ChannelItem) -> str:
    name = item.name
    url = item.url
    match_cctv_url = False
    for pat in CCTV_URL_PATTERNS:
        if re.search(pat, url):
            match_cctv_url = True
            break
    if match_cctv_url or REGEX_CCTV_PREFIX.search(name):
        return "央视频道,#genre#"
    if "影" in name:
        return "电影频道,#genre#"
    if "卫视" in name:
        return "卫视频道,#genre#"
    if "河南" in name and "河南卫视" not in name:
        return "河南频道,#genre#"
    return "其他频道,#genre#"

def sort_cctv_group(items: List[ChannelItem]) -> List[ChannelItem]:
    digit = []
    other = []
    for ch in items:
        if ch.cctv_digit and ch.cctv_digit in CCTV_VALID_NUMBERS:
            digit.append(ch)
        else:
            other.append(ch)
    digit.sort(key=lambda x: int(x.cctv_digit))
    return digit + other

def deduplicate_channel_list(channels: List[ChannelItem]) -> List[ChannelItem]:
    seen = set()
    out = []
    for ch in channels:
        if ch.url not in seen:
            seen.add(ch.url)
            out.append(ch)
    return out

def generate_complement_cctv_from_sou() -> List[ChannelItem]:
    complement = []
    if not OUTPUT_FILE.exists():
        return complement
    # 修复：捕获读取临时文件IO异常
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            all_lines = [line.strip() for line in f.readlines() if line.strip()]
    except IOError as e:
        print(f"⚠️ 读取临时sou.txt失败，跳过CCTV模板补全：{str(e)}")
        return complement

    template_map: Dict[str, str] = {}
    for line in all_lines:
        if "," not in line or "#genre#" in line:
            continue
        name, url = line.split(",", maxsplit=1)
        m1 = FORMAT1_PATTERN.search(url)
        if m1:
            n = m1.group(1)
            template_map["fmt1"] = url.replace(f"cctv{n}.m3u8", "cctv{n}.m3u8")
            continue
        m2 = FORMAT2_PATTERN.search(url)
        if m2:
            # 修复分组越界：判断分组存在再取值
            pre = m2.group(1) if m2.group(1) else "000"
            template_map["fmt2"] = url.replace(f"{pre}{m2.group(2)}_1.m3u8", "{pre}{n:02d}_1.m3u8")
            continue
        m3 = FORMAT3_PATTERN.search(url)
        if m3:
            template_map["fmt3"] = re.sub(r"/hls/(30)?\d{1,2}/index\.m3u8", r"/hls/{pre}{n}/index.m3u8", url)
            continue
        m4 = FORMAT4_PATTERN.search(url)
        if m4:
            n = m4.group(1)
            template_map["fmt4"] = url.replace(f"cctv{n}hd.m3u8", "cctv{n}hd.m3u8")
            continue

    # fmt1
    if "fmt1" in template_map:
        tpl = template_map["fmt1"]
        for num in range(1, 18):
            complement.append(ChannelItem(f'#EXTINF:-1,CCTV{num}', tpl.format(n=num), f"CCTV{num}", str(num)))
    # fmt2
    if "fmt2" in template_map:
        tpl = template_map["fmt2"]
        for num in range(1, 18):
            complement.append(ChannelItem(f'#EXTINF:-1,CCTV{num}', tpl.format(pre="000", n=f"{num:02d}"), f"CCTV{num}", str(num)))
    # fmt3
    if "fmt3" in template_map:
        tpl = template_map["fmt3"]
        for raw_n in range(1, 19):
            url = tpl.format(pre="", n=raw_n)
            if raw_n == 6:
                name = "CCTV5+"
                digit = None
            elif raw_n < 6:
                name = f"CCTV{raw_n}"
                digit = str(raw_n)
            else:
                name = f"CCTV{raw_n - 1}"
                digit = str(raw_n - 1)
            complement.append(ChannelItem(f'#EXTINF:-1,{name}', url, name, digit))
    # fmt4 hd
    if "fmt4" in template_map:
        tpl = template_map["fmt4"]
        for num in range(1, 18):
            complement.append(ChannelItem(f'#EXTINF:-1,CCTV{num}', tpl.format(n=num), f"CCTV{num}", str(num)))
    print(f"✅ 提取模板生成补全CCTV链接：{len(complement)} 条")
    return complement

def main():
    # 前置检测ffmpeg
    if not check_ffmpeg():
        print("❌ 未检测到ffmpeg，请安装并配置环境变量后重试！测速功能无法使用")
        raise SystemExit(1)

    all_channels: List[ChannelItem] = []
    seen_urls: Set[str] = set()

    # 加载源
    source_urls = load_sources()
    print(f"加载 {len(source_urls)} 个远程源地址")
    for src in source_urls:
        chs = download_and_parse(src)
        print(f"解析 {src} 获取 {len(chs)} 条频道")
        for ch in chs:
            if ch.url not in seen_urls:
                seen_urls.add(ch.url)
                all_channels.append(ch)

    # 生成探测CCTV
    probe = generate_cctv_probe_channels()
    for ch in probe:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            all_channels.append(ch)
    print(f"去重后待检测频道总数：{len(all_channels)}")
    valid_all = all_channels
    print(f"\n全部{len(valid_all)}条频道进入测速，无丢弃")

    group_container: Dict[str, List[ChannelItem]] = {g: [] for g in GROUP_ORDER}
    passed = 0
    task_map = {}
    print(f"\n开始并发测速，线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        for ch in valid_all:
            task_map[exe.submit(check_stream_valid, ch.url)] = ch
        finished = 0
        for fut in as_completed(task_map):
            finished += 1
            ch = task_map[fut]
            try:
                ok, h = fut.result()
            except Exception as e:
                print(f"[{finished}/{len(valid_all)}] 任务异常 {ch.name}: {str(e)}")
                continue
            print(f"[{finished}/{len(valid_all)}] {ch.name} | {ch.url[:70]}...")
            if ok and h >= MIN_HEIGHT:
                tag = classify_channel(ch)
                group_container[tag].append(ch)
                passed += 1
                print(f"✅ 通过 | {h}P | {tag.split(',#genre#')[0]}")
            else:
                print(f"❌ 失效/分辨率不足 ok={ok} h={h}")
    print(f"\n第一轮有效频道：{passed}")

    # 写入临时文件（捕获IO异常）
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            for tag in GROUP_ORDER:
                items = deduplicate_channel_list(group_container[tag])
                if not items:
                    continue
                if tag == "央视频道,#genre#":
                    items = sort_cctv_group(items)
                for ch in items:
                    f.write(f"{ch.name},{ch.url}\n")
        print(f"\n✅ 第一轮临时文件生成完成：{OUTPUT_FILE.name}")
    except IOError as e:
        print(f"❌ 写入临时sou.txt失败：{str(e)}")
        raise SystemExit(1)

    # 补全CCTV链接
    complement = generate_complement_cctv_from_sou()
    new_comp = []
    for ch in complement:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            new_comp.append(ch)
    complement = new_comp
    print(f"\n去重后补全待检测：{len(complement)}")
    valid_comp = complement
    print(f"补全链接{len(valid_comp)}条全部测速")

    # 二次测速
    task_map2 = {}
    print(f"\n校验补全CCTV链接，线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        for ch in valid_comp:
            task_map2[exe.submit(check_stream_valid, ch.url)] = ch
        fin2 = 0
        add_pass = 0
        for fut in as_completed(task_map2):
            fin2 += 1
            ch = task_map2[fut]
            try:
                ok, h = fut.result()
            except Exception as e:
                print(f"[补全{fin2}/{len(valid_comp)}] 异常 {ch.name}: {str(e)}")
                continue
            print(f"[补全{fin2}/{len(valid_comp)}] {ch.name} | {ch.url[:70]}...")
            if ok and h >= MIN_HEIGHT:
                tag = classify_channel(ch)
                group_container[tag].append(ch)
                add_pass += 1
                print(f"✅ 补全通过 | {h}P | {tag.split(',#genre#')[0]}")
            else:
                print(f"❌ 补全链接失效 ok={ok} h={h}")
    passed += add_pass
    print(f"\n补全新增有效：{add_pass}，总有效频道：{passed}")

    # 最终输出OK影视分类文件
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            for tag in GROUP_ORDER:
                raw_items = group_container[tag]
                unique = deduplicate_channel_list(raw_items)
                if not unique:
                    continue
                f.write(f"{tag}\n")
                if tag == "央视频道,#genre#":
                    unique = sort_cctv_group(unique)
                for ch in unique:
                    f.write(f"{ch.name},{ch.url}\n")
        print(f"\n✅ OK影视分类sou.txt生成完毕：{OUTPUT_FILE.name}")
    except IOError as e:
        print(f"❌ 最终写入sou.txt失败：{str(e)}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
