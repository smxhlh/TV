import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass
from pathlib import Path

# ====================== 全局配置 ======================
SOURCE_LIST_PATH = Path("sources.list")
OUTPUT_FILE = Path("sou.txt")
TIMEOUT_HTTP = 10
FFMPEG_TIMEOUT = 12
MIN_HEIGHT = 720
MAX_WORKERS = 10

# CCTV固定模板【用于URL匹配识别 + 自动生成探测链接】
# 格式：(url模板字符串, 名称前缀)
CCTV_GENERATE_TEMPLATES = [
    ("http://118.81.195.79:9003/hls/{n}/index.m3u8", "CCTV{n}"),
    ("http://74.91.26.218:82/live/cctv{n}hd.m3u8", "CCTV{n}"),
]
CCTV_NUM_RANGE = list(range(1, 18))  # 1~17

# URL正则匹配（解析识别CCTV链接）
CCTV_URL_PATTERNS = [
    r"http://69\.30\.245\.50/live/cctv(\d{1,2})\.m3u8",
    r"http://74\.91\.26\.218:82/live/cctv(\d{1,2})hd\.m3u8",
    r"http://218\.13\.170\.98:9901/tsfile/live/000(\d{1,2})_1\.m3u8",
    r"http://112\.46\.85\.60:8009/hls/(\d{1,2})/index\.m3u8",
    r"http://cssbyd\.imwork\.net:8082/hls/(\d{1,2})/index\.m3u8",
    r"http://118\.81\.195\.79:9003/hls/(\d{1,2})/index\.m3u8", # 新增探测地址正则
]
CCTV_VALID_NUMBERS = set(str(i) for i in CCTV_NUM_RANGE)

REGEX_CCTV_PREFIX = re.compile(r"CCTV-?")
REGEX_CCTV_NUM = re.compile(r"CCTV-?(\d{1,2})")

# 保留分组，无匹配直接丢弃
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


def generate_cctv_probe_channels() -> List[ChannelItem]:
    """自动生成两套规则CCTV1~17探测频道"""
    probe_list = []
    for url_tpl, name_tpl in CCTV_GENERATE_TEMPLATES:
        for num in CCTV_NUM_RANGE:
            url = url_tpl.format(n=num)
            ch_name = name_tpl.format(n=num)
            probe_list.append(
                ChannelItem(
                    extinf=f'#EXTINF:-1,{ch_name}',
                    url=url,
                    name=ch_name,
                    cctv_digit=str(num)
                )
            )
    print(f"✅ 自动生成探测频道数量：{len(probe_list)}")
    return probe_list


def load_sources() -> List[str]:
    with open(SOURCE_LIST_PATH, "r", encoding="utf-8") as f:
        lines = [i.strip() for i in f.readlines() if i.strip() and not i.startswith("#")]
    return lines


def download_m3u(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=TIMEOUT_HTTP)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None


def parse_m3u(raw_text: str) -> List[ChannelItem]:
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
    name = item.name
    url = item.url

    match_cctv_url = False
    for pattern in CCTV_URL_PATTERNS:
        if re.match(pattern, url):
            match_cctv_url = True
            break
    if match_cctv_url and REGEX_CCTV_PREFIX.search(name):
        return "央视频道,#genre#"

    if "影" in name:
        return "电影频道,#genre#"

    if "卫视" in name:
        return "卫视频道,#genre#"

    if "河南" in name and "河南卫视" not in name:
        return "河南频道,#genre#"

    return None


def sort_cctv_group(items: List[ChannelItem]) -> List[ChannelItem]:
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

    # 步骤1：加载远程m3u源
    source_urls = load_sources()
    print(f"加载 {len(source_urls)} 个远程m3u源")
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

    # 步骤2：【新增】自动生成CCTV规则探测链接，加入待测试列表
    probe_channels = generate_cctv_probe_channels()
    for ch in probe_channels:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            all_channels.append(ch)

    print(f"去重后全部待检测频道总数：{len(all_channels)}")

    # 步骤3：多线程并发测速校验
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

            print(f"[{finished}/{len(all_channels)}] {ch.name} | {ch.url[:70]}...")
            if ok and height >= MIN_HEIGHT:
                group_tag = classify_channel(ch)
                if group_tag is not None:
                    group_container[group_tag].append(ch)
                    passed += 1
                    print(f"✅ 通过 | {height}P | {group_tag.split(',#genre#')[0]}")
                else:
                    print(f"❌ 测速正常，无匹配分组，丢弃")
            else:
                print(f"❌ 链接失效或分辨率不足 {ok} {height}")

    print(f"\n最终保留有效频道总数：{passed}")

    # 步骤4：输出 sou.txt 名称,链接
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            items = group_container[group_tag]
            if not items:
                continue
            if group_tag == "央视频道,#genre#":
                items = sort_cctv_group(items)
            for ch in items:
                f.write(f"{ch.name},{ch.url}\n")

    print(f"\n✅ 文件生成完成：{OUTPUT_FILE.name}")
    print(f"在线地址：https://github.com/smxhlh/TV/blob/main/sou.txt")


if __name__ == "__main__":
    main()
