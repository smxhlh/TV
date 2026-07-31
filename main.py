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
CCTV_NUM_RANGE = list(range(1, 18))  # CCTV1~17
# 请求头模拟浏览器，解决PHP防盗链拦截
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/plain,application/x-mpegurl,application/vnd.apple.mpegurl,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive"
}
# 正则：提取模板A /000{n}_1.m3u8
PATTERN_TSFILE_TPL = re.compile(r"(http://.+?/)000(\d{1,2})_1(\.m3u8\?.*)?")
# 正则：提取模板B /hls/{n}/xxx.m3u8
PATTERN_HLS_TPL = re.compile(r"(http://.+?/hls/)(\d{1,2})(/.*\.m3u8)")
# URL正则匹配识别CCTV链接
CCTV_URL_PATTERNS = [
    r"http://69\.30\.245\.50/live/cctv(\d{1,2})\.m3u8",
    r"http://74\.91\.26\.218:82/live/cctv(\d{1,2})hd\.m3u8",
    r"tsfile/live/000(\d{1,2})_1\.m3u8",
    r"/hls/(\d{1,2})/live\.m3u8",
    r"/hls/(\d{1,2})/index\.m3u8",
    r"http://118\.81\.195\.79:9003/hls/(\d{1,2})/index\.m3u8",
]
CCTV_VALID_NUMBERS = set(str(i) for i in CCTV_NUM_RANGE)
REGEX_CCTV_PREFIX = re.compile(r"CCTV-?")
REGEX_CCTV_NUM = re.compile(r"CCTV-?(\d{1,2})")
# 分组顺序
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
    with open(SOURCE_LIST_PATH, "r", encoding="utf-8") as f:
        lines = [i.strip() for i in f.readlines() if i.strip() and not i.startswith("#")]
    return lines
def download_m3u(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=TIMEOUT_HTTP,
            allow_redirects=True
        )
        resp.raise_for_status()
        html_signatures = ["<html", "<!DOCTYPE html", "<head", "<body"]
        raw = resp.text
        lower_raw = raw.lower()
        for sig in html_signatures:
            if sig in lower_raw:
                print(f"[拦截HTML页面] {url} 返回网页而非直播源")
                return None
        raw = raw.lstrip('\ufeff').strip()
        return raw
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None
def is_standard_m3u(text: str) -> bool:
    text_clean = text.strip().lower()
    return text_clean.startswith("#extm3u") or "#extinf" in text_clean
def parse_m3u(raw_text) -> List[ChannelItem]:
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    extinf_cache = ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#extm3u") or (line.startswith("#") and not line.startswith("#EXTINF:")):
            continue
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
def parse_txt_source(raw_text: str) -> List[ChannelItem]:
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," not in line:
            continue
        name, url = line.split(",", maxsplit=1)
        name = name.strip()
        url = url.strip()
        if not url.startswith("http"):
            continue
        digit_match = REGEX_CCTV_NUM.search(name)
        digit = digit_match.group(1) if digit_match else None
        items.append(ChannelItem(
            extinf=f'#EXTINF:-1,{name}',
            url=url,
            name=name,
            cctv_digit=digit
        ))
    return items
def download_and_parse(url: str) -> List[ChannelItem]:
    raw_text = download_m3u(url)
    if not raw_text:
        return []
    if is_standard_m3u(raw_text):
        return parse_m3u(raw_text)
    else:
        return parse_txt_source(raw_text)
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
        return False
def classify_channel(item: ChannelItem) -> Optional[str]:
    name = item.name
    url = item.url
    match_cctv_url = False
    for pattern in CCTV_URL_PATTERNS:
        if re.search(pattern, url):
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
def extract_probe_templates(valid_items: List[ChannelItem]) -> List[str]:
    """从首轮有效CCTV链接提取模板A、模板B"""
    template_set = set()
    for item in valid_items:
        url = item.url
        # 提取模板A 000{n}_1
        ts_match = PATTERN_TSFILE_TPL.search(url)
        if ts_match:
            prefix, _, suffix = ts_match.groups()
            tpl = f"{prefix}000{{n}}_1{suffix}"
            template_set.add(tpl)
        # 提取模板B hls/{n}
        hls_match = PATTERN_HLS_TPL.search(url)
        if hls_match:
            prefix, _, suffix = hls_match.groups()
            tpl = f"{prefix}{{n}}{suffix}"
            template_set.add(tpl)
    templates = list(template_set)
    print(f"\n✅ 从首轮有效CCTV提取到 {len(tpl)} 套探测模板：")
    for t in templates:
        print(f" - {t}")
    return templates
def generate_probe_from_templates(templates: List[str]) -> List[ChannelItem]:
    """根据模板批量生成CCTV1~17探测链接"""
    probe_list = []
    for tpl in templates:
        for num in CCTV_NUM_RANGE:
            url = tpl.format(n=num)
            ch_name = f"CCTV{num}"
            probe_list.append(
                ChannelItem(
                    extinf=f'#EXTINF:-1,{ch_name}',
                    url=url,
                    name=ch_name,
                    cctv_digit=str(num)
                )
            )
    print(f"\n✅ 模板生成待二次探测链接：{len(probe_list)} 条")
    return probe_list
# 【修复报错核心函数】先定义finished再循环，消除UnboundLocalError
def batch_check_channels(channels: List[ChannelItem], seen: Set[str]) -> Tuple[List[ChannelItem], Set[str]]:
    valid_res: List[ChannelItem] = []
    task_map = {}
    finished = 0  # 提前初始化变量，修复报错
    total = len(channels)
    print(f"\n开始并发测速，待检测 {total} 条，并发数 {MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 全部任务入队
        for ch in channels:
            if ch.url in seen:
                continue
            future = executor.submit(check_stream_valid, ch.url)
            task_map[future] = ch
        # 遍历完成任务
        for future in as_completed(task_map):
            finished += 1
            ch = task_map[future]
            try:
                ok, height = future.result()
            except Exception as e:
                print(f"[{finished}/{total}] 任务异常 {ch.name}: {str(e)}")
                continue
            print(f"[{finished}/{total}] {ch.name} | {ch.url[:70]}...")
            if ok and height >= MIN_HEIGHT:
                if ch.url not in seen:
                    seen.add(ch.url)
                    valid_res.append(ch)
                print(f"✅ 通过 | {height}P")
            else:
                print(f"❌ 失效/分辨率不足 ok={ok} height={height}")
    return valid_res, seen
def main():
    all_seen_urls: Set[str] = set()
    group_container: Dict[str, List[ChannelItem]] = {g: [] for g in GROUP_ORDER}
    # ========== 阶段1：加载远程源并解析 ==========
    print("===== 阶段1：加载并解析所有远程源 =====")
    source_urls = load_sources()
    print(f"读取 sources.list 共 {len(source_urls)} 个远程地址")
    raw_all_channels: List[ChannelItem] = []
    for src in source_urls:
        channels = download_and_parse(src)
        print(f"解析 {src} 获取 {len(channels)} 条频道")
        for ch in channels:
            raw_all_channels.append(ch)
    print(f"\n待首轮测速总频道：{len(raw_all_channels)}")
    # 首轮测速所有原始频道
    first_round_valid, all_seen_urls = batch_check_channels(raw_all_channels, all_seen_urls)
    print(f"\n===== 阶段1完成：首轮有效频道 {len(first_round_valid)} 条 =====")
    # 首轮有效频道先存入分组
    for ch in first_round_valid:
        tag = classify_channel(ch)
        if tag:
            group_container[tag].append(ch)
    # ========== 阶段2：提取模板生成CCTV探测链接 ==========
    print("\n===== 阶段2：动态提取模板并生成CCTV1~17探测链接 =====")
    probe_templates = extract_probe_templates(first_round_valid)
    second_round_valid = []
    if not probe_templates:
        print("未提取到000{n}/hls{n}模板，跳过二次探测")
    else:
        probe_channels = generate_probe_from_templates(probe_templates)
        # 二次测速模板生成的CCTV链接
        print("\n===== 阶段3：二次测速动态模板链接 =====")
        second_round_valid, all_seen_urls = batch_check_channels(probe_channels, all_seen_urls)
        print(f"\n===== 阶段3完成：二次新增有效CCTV {len(second_round_valid)} 条 =====")
        # 二次有效频道并入分组
        for ch in second_round_valid:
            tag = classify_channel(ch)
            if tag:
                group_container[tag].append(ch)
    # ========== 阶段4：分组排序输出sou.txt ==========
    print("\n===== 阶段4：分组排序生成最终 sou.txt =====")
    total_final = sum(len(lst) for lst in group_container.values())
    print(f"最终全部有效频道总数：{total_final}")
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
