import re
import time
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass
from pathlib import Path

# ====================== 全局配置 ======================
SOURCE_LIST_PATH = Path("sources.list")
OUTPUT_FILE = Path("sou.txt")  # OK影视格式输出文件
TIMEOUT_HTTP = 10
FFMPEG_TIMEOUT = 12
MIN_HEIGHT = 720  # 最低分辨率720P
MAX_WORKERS = 10  # 并发测速线程，Actions推荐8-12

# 需要匹配的CCTV URL模板正则
CCTV_URL_PATTERNS = [
    r"http://69\.30\.245\.50/live/cctv(\d{1,2})\.m3u8",
    r"http://74\.91\.26\.218:82/live/cctv(\d{1,2})hd\.m3u8",
    r"http://218\.13\.170\.98:9901/tsfile/live/000(\d{1,2})_1\.m3u8",
    r"http://112\.46\.85\.60:8009/hls/(\d{1,2})/index\.m3u8",
    r"http://cssbyd\.imwork\.net:8082/hls/(\d{1,2})/index\.m3u8",
]
# CCTV 1~17有效数字范围
CCTV_VALID_NUMBERS = set(str(i) for i in range(1, 18))

# 频道名称正则
REGEX_CCTV_PREFIX = re.compile(r"CCTV-?")
REGEX_CCTV_NUM = re.compile(r"CCTV-?(\d{1,2})")

# 保留分组（移除【其他】，不匹配全部丢弃）
GROUP_ORDER = [
    "央视频道,#genre#",
    "电影频道,#genre#",
    "卫视频道,#genre#",
    "河南频道,#genre#"
]

@dataclass
class ChannelItem:
    extinf: str
    url: str
    name: str
    cctv_digit: Optional[str] = None

def load_sources() -> List[str]:
    """读取远程源地址列表"""
    with open(SOURCE_LIST_PATH, "r", encoding="utf-8") as f:
        lines = [i.strip() for i in f.readlines() if i.strip() and not i.startswith("#")]
    return lines

def download_m3u(url: str) -> Optional[str]:
    """下载远程m3u文本"""
    try:
        resp = requests.get(url, timeout=TIMEOUT_HTTP)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None

def parse_m3u(raw_text: str) -> List[ChannelItem]:
    """解析标准EXTM3U文本"""
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    extinf_cache = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            extinf_cache = line
        elif line.startswith("http") and extinf_cache:
            match_name = re.search(r',([^,]+)$', extinf_cache)
            name = match_name.group(1).strip() if match_name else "未知频道"
            digit_match = REGEX_CCTV_NUM.search(name)
            digit = digit_match.group(1) if digit_match else None
            items.append(ChannelItem(extinf=extinf_cache, url=line, name=name, cctv_digit=digit))
            extinf_cache = ""
    return items

def check_stream_valid(url: str) -> Tuple[bool, Optional[int]]:
    """ffmpeg检测流有效性与分辨率"""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v", "error",
        "-rtbufsize", "1M",
        "-i", url,
        "-t", "2",
        "-f", "null", "-"
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(timeout=FFMPEG_TIMEOUT)
        res_match = re.search(r"(\d+)x(\d+)", stderr)
        height = int(res_match.group(2)) if res_match else None
        valid = height is not None
        return valid, height
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        return False, None
    except Exception:
        if proc:
            try:
                proc.kill()
            except:
                pass
        return False, None

def classify_channel(item: ChannelItem) -> Optional[str]:
    """
    分类逻辑：返回分组标签；无法匹配返回None，直接丢弃
    1.URL匹配CCTV模板 + 名称含CCTV前缀 → 央视频道
    2.名称包含【影】→电影频道
    3.包含卫视 →卫视频道
    4.含河南，不含河南卫视 →河南频道
    其余返回None，丢弃
    """
    name = item.name
    url = item.url

    # CCTV匹配判断
    match_cctv_url = False
    for pattern in CCTV_URL_PATTERNS:
        if re.match(pattern, url):
            match_cctv_url = True
            break
    if match_cctv_url and REGEX_CCTV_PREFIX.search(name):
        return "央视频道,#genre#"

    # 电影频道
    if "影" in name:
        return "电影频道,#genre#"

    # 卫视频道
    if "卫视" in name:
        return "卫视频道,#genre#"

    # 河南频道，排除河南卫视
    if "河南" in name and "河南卫视" not in name:
        return "河南频道,#genre#"

    # 不满足任意分组 → 返回None，直接丢弃
    return None

def sort_cctv_group(items: List[ChannelItem]) -> List[ChannelItem]:
    """央视频道内排序：CCTV1-17在前，4K/外文CCTV在后"""
    digit_channels: List[ChannelItem] = []
    non_digit_channels: List[ChannelItem] = []
    for ch in items:
        if ch.cctv_digit and ch.cctv_digit in CCTV_VALID_NUMBERS:
            digit_channels.append(ch)
        else:
            non_digit_channels.append(ch)
    digit_channels.sort(key=lambda x: int(x.cctv_digit))
    return digit_channels + non_digit_channels

def main():
    all_channels: List[ChannelItem] = []
    seen_urls: Set[str] = set()

    source_urls = load_sources()
    print(f"加载 {len(source_urls)} 个远程源")
    for src in source_urls:
        text = download_m3u(src)
        if not text:
            continue
        channels = parse_m3u(text)
        print(f"解析 {src} 获取 {len(channels)} 条频道")
        for ch in channels:
            if ch.url not in seen_urls:
                seen_urls.add(ch.url)
                all_channels.append(ch)
    print(f"去重后总频道数量：{len(all_channels)}")

    # 多线程并发测速
    group_container: Dict[str, List[ChannelItem]] = {g: [] for g in GROUP_ORDER}
    passed = 0
    task_map = {}

    print(f"\n开始并发测速，并发线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for ch in all_channels:
            future = executor.submit(check_stream_valid, ch.url)
            task_map[future] = ch

        finished = 0
        for future in as_completed(task_map):
            finished += 1
            ch = task_map[future]
            try:
                ok, height = future.result()
            except Exception as e:
                print(f"[{finished}/{len(all_channels)}] 任务异常 {ch.name}: {str(e)}")
                continue

            print(f"[{finished}/{len(all_channels)}] {ch.name} | {ch.url[:60]}...")
            if ok and height >= MIN_HEIGHT:
                group_tag = classify_channel(ch)
                # group_tag为None代表不属于保留分组，直接丢弃
                if group_tag is not None:
                    group_container[group_tag].append(ch)
                    passed += 1
                    print(f"✅ 通过 | 分辨率 {height}P | 分组：{group_tag.split(',#genre#')[0]}")
                else:
                    print(f"❌ 通过测速，但无匹配分组，丢弃")
            else:
                print(f"❌ 丢弃 | 有效:{ok} height:{height}")

    print(f"\n最终保留有效频道总数：{passed}")

    # 输出 OK影视格式 sou.txt 【名称,链接】
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            items = group_container[group_tag]
            if not items:
                continue
            # 央视频道执行内部排序
            if group_tag == "央视频道,#genre#":
                items = sort_cctv_group(items)
            # 写入 名称,url
            for ch in items:
                line = f"{ch.name},{ch.url}"
                f.write(line + "\n")

    print(f"\n✅ 文件生成完成 -> {OUTPUT_FILE.resolve()}")
    print(f"在线访问地址：https://github.com/smxhlh/TV/blob/main/sou.txt")

if __name__ == "__main__":
    main()
