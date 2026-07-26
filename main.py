import re
import time
import subprocess
import requests
from typing import List, Dict, Tuple, Set
from dataclasses import dataclass
from pathlib import Path

# ====================== 全局配置 ======================
SOURCE_LIST_PATH = Path("sources.list")
OUTPUT_M3U = Path("output/sorted.m3u")
TIMEOUT_HTTP = 10
FFMPEG_TIMEOUT = 12
MIN_HEIGHT = 720  # 最低分辨率720P
# 需要匹配的CCTV URL模板正则（*替换为数字捕获组）
CCTV_URL_PATTERNS = [
    r"http://69\.30\.245\.50/live/cctv(\d{1,2})\.m3u8",
    r"http://74\.91\.26\.218:82/live/cctv(\d{1,2})hd\.m3u8",
    r"http://218\.13\.170\.98:9901/tsfile/live/000(\d{1,2})_1\.m3u8",
    r"http://112\.46\.85\.60:8009/hls/(\d{1,2})/index\.m3u8",
    r"http://cssbyd\.imwork\.net:8082/hls/(\d{1,2})/index\.m3u8",
]
# CCTV 1~17有效范围
CCTV_VALID_NUMBERS = set(str(i) for i in range(1, 18))

# 频道名称正则：匹配 CCTV1 / CCTV-1 / CCTV1(xxx) / CCTV-1(xxx)
REGEX_CCTV_NAME = re.compile(r"CCTV-?(\d{1,2})")

# 分组顺序【优先级从上至下，不可乱序】
GROUP_ORDER = [
    "央视频道,#genre#",
    "电影频道,#genre#",
    "卫视频道,#genre#",
    "河南频道,#genre#",
    "其他,#genre#"
]

@dataclass
class ChannelItem:
    extinf: str
    url: str
    name: str


def load_sources() -> List[str]:
    """读取远程源地址列表"""
    with open(SOURCE_LIST_PATH, "r", encoding="utf-8") as f:
        lines = [i.strip() for i in f.readlines() if i.strip() and not i.startswith("#")]
    return lines


def download_m3u(url: str) -> str | None:
    """下载远程m3u文本，异常返回None"""
    try:
        resp = requests.get(url, timeout=TIMEOUT_HTTP)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None


def parse_m3u(raw_text: str) -> List[ChannelItem]:
    """解析标准EXTM3U文本，提取频道"""
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    extinf_cache = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            extinf_cache = line
        elif line.startswith("http") and extinf_cache:
            # 提取频道名称
            match_name = re.search(r',([^,]+)$', extinf_cache)
            name = match_name.group(1).strip() if match_name else "未知频道"
            items.append(ChannelItem(extinf=extinf_cache, url=line, name=name))
            extinf_cache = ""
    return items


def check_stream_valid(url: str) -> Tuple[bool, int | None]:
    """
    使用ffmpeg检测流有效性 + 获取视频高度
    返回 (是否可用, 画面高度)
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v", "error",
        "-rtbufsize", "1M",
        "-i", url,
        "-t", "2",
        "-f", "null", "-"
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate(timeout=FFMPEG_TIMEOUT)
        # 寻找分辨率信息
        res_match = re.search(r"(\d+)x(\d+)", stderr)
        height = None
        if res_match:
            height = int(res_match.group(2))
        # 进程正常结束且识别到视频流视为有效
        valid = height is not None
        return valid, height
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, None
    except Exception:
        return False, None


def classify_channel(item: ChannelItem) -> str:
    """
    核心分类函数，严格遵循需求规则
    返回分组标签 GROUP_ORDER 内字符串
    """
    name = item.name
    url = item.url

    # 1. 判断是否符合【央视频道,#genre#】双重条件
    cctv_num_in_url = None
    for pattern in CCTV_URL_PATTERNS:
        m = re.match(pattern, url)
        if m:
            cctv_num_in_url = m.group(1)
            break
    if cctv_num_in_url and cctv_num_in_url in CCTV_VALID_NUMBERS:
        # URL包含合法1~17，再校验频道名称是否匹配CCTV数字
        name_match = REGEX_CCTV_NAME.search(name)
        if name_match:
            name_num = name_match.group(1)
            if name_num in CCTV_VALID_NUMBERS:
                # 排除 CCTV4K、CCTV字母频道（名称不命中数字则直接跳过）
                return "央视频道,#genre#"

    # 2. 电影频道：包含【影】
    if "影" in name:
        return "电影频道,#genre#"

    # 3. 卫视频道：包含卫视
    if "卫视" in name:
        return "卫视频道,#genre#"

    # 4. 河南频道：含河南，排除河南卫视
    if "河南" in name and "河南卫视" not in name:
        return "河南频道,#genre#"

    # 5. 其他分组关键词
    other_keywords = {"动画", "相声", "足球", "音乐"}
    for kw in other_keywords:
        if kw in name:
            return "其他,#genre#"

    # 兜底
    return "其他,#genre#"


def main():
    Path(OUTPUT_M3U.parent).mkdir(exist_ok=True)
    source_urls = load_sources()
    all_channels: List[ChannelItem] = []
    seen_urls: Set[str] = set()

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

    # 流检测过滤
    valid_channels: Dict[str, List[ChannelItem]] = {g: [] for g in GROUP_ORDER}
    passed = 0
    for idx, ch in enumerate(all_channels):
        print(f"[{idx+1}/{len(all_channels)}] 检测：{ch.name} | {ch.url[:60]}...")
        ok, height = check_stream_valid(ch.url)
        if ok and height >= MIN_HEIGHT:
            group = classify_channel(ch)
            valid_channels[group].append(ch)
            passed += 1
            print(f"✅ 通过 | 分辨率 {height}P | 分组：{group}")
        else:
            print(f"❌ 丢弃 | 有效:{ok} height:{height}")

    print(f"\n有效频道总数（≥720P）：{passed}")

    # 输出标准M3U文件
    with open(OUTPUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for group_tag in GROUP_ORDER:
            items = valid_channels[group_tag]
            if not items:
                continue
            f.write(f"\n#EXTGRP:{group_tag.split(',#genre#')[0]}\n")
            for ch in items:
                # 追加分组标签到extinf
                new_extinf = re.sub(r'(,.*)$', f',{group_tag}', ch.extinf)
                f.write(f"{new_extinf}\n{ch.url}\n")
    print(f"\n✅ 文件输出完成 -> {OUTPUT_M3U}")


if __name__ == "__main__":
    main()
