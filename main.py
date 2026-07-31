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
# 请求头模拟浏览器，解决PHP防盗链拦截
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/plain,application/x-mpegurl,application/vnd.apple.mpegurl,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive"
}
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
# 新增：三种CCTV链接格式正则，用于从已输出sou.txt提取补全缺失CCTV源
FORMAT1_PATTERN = re.compile(r"cctv(\d{1,2})\.m3u8")          # {n}.m3u8 n1-17 CCTVn
FORMAT2_PATTERN = re.compile(r"000(\d{1,2})_1\.m3u8")        # {n}_1.m3u8 n1-17 CCTVn
FORMAT3_PATTERN = re.compile(r"/hls/(\d{1,2})/index\.m3u8") # {n}/index.m3u8 n1-18 n6=CCTV5+,n>6对应CCTV(n-1)

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
    """修复：增加UA、允许重定向、自动处理编码、过滤HTML报错页面"""
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=TIMEOUT_HTTP,
            allow_redirects=True
        )
        resp.raise_for_status()
        # 过滤PHP返回HTML页面（不是M3U源）
        html_signatures = ["<html", "<!DOCTYPE html", "<head", "<body"]
        raw = resp.text
        lower_raw = raw.lower()
        for sig in html_signatures:
            if sig in lower_raw:
                print(f"[拦截HTML页面] {url} 返回网页而非直播源")
                return None
        # 统一UTF-8，清除BOM、首尾空白
        raw = raw.lstrip('\ufeff').strip()
        return raw
    except Exception as e:
        print(f"[下载失败] {url} : {str(e)}")
        return None
def is_standard_m3u(text: str) -> bool:
    """判断是否为M3U（兼容PHP动态输出，优先#EXTM3U，其次#EXTINF）"""
    text_clean = text.strip().lower()
    # 标准M3U必须以#extm3u开头，其次包含#extinf
    return text_clean.startswith("#extm3u") or "#extinf" in text_clean
def parse_m3u(raw_text: str) -> List[ChannelItem]:
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    extinf_cache = ""
    for line in lines:
        line = line.strip()
        # 跳过#EXTM3U头部、空行、纯注释
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
# 新增：解析逗号分隔txt直播源（名称,url）
def parse_txt_source(raw_text: str) -> List[ChannelItem]:
    items: List[ChannelItem] = []
    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        # 跳过空行、注释行
        if not line or line.startswith("#"):
            continue
        # 必须包含逗号分割名称和链接
        if "," not in line:
            continue
        name, url = line.split(",", maxsplit=1)
        name = name.strip()
        url = url.strip()
        # 只保留http直播链接
        if not url.startswith("http"):
            continue
        # 提取CCTV数字编号
        digit_match = REGEX_CCTV_NUM.search(name)
        digit = digit_match.group(1) if digit_match else None
        items.append(ChannelItem(
            extinf=f'#EXTINF:-1,{name}',
            url=url,
            name=name,
            cctv_digit=digit
        ))
    return items
# 修复：统一下载+智能区分PHP动态M3U/普通txt
def download_and_parse(url: str) -> List[ChannelItem]:
    raw_text = download_m3u(url)
    if not raw_text:
        return []
    # 优先判断标准M3U（含#EXTM3U/#EXTINF），PHP动态m3u走这里
    if is_standard_m3u(raw_text):
        return parse_m3u(raw_text)
    else:
        # 仅无M3U标记时才按逗号txt解析
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

# 新增：从已生成sou.txt读取链接，提取三种CCTV模板，生成完整1~17补全链接
def generate_complement_cctv_from_sou() -> List[ChannelItem]:
    complement_list = []
    if not OUTPUT_FILE.exists():
        return complement_list
    # 读取第一轮生成的sou.txt
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        sou_lines = [line.strip() for line in f.readlines() if line.strip() and "," in line]
    # 提取所有三种模板基础URL模板
    template_map: Dict[str, str] = {} # key:模板类型标识, value:基础url模板
    for line in sou_lines:
        name, url = line.split(",", maxsplit=1)
        # 匹配格式1 cctv{n}.m3u8
        m1 = FORMAT1_PATTERN.search(url)
        if m1:
            n = m1.group(1)
            base_tpl = url.replace(f"cctv{n}.m3u8", "cctv{n}.m3u8")
            template_map["fmt1"] = base_tpl
            continue
        # 匹配格式2 000{n}_1.m3u8
        m2 = FORMAT2_PATTERN.search(url)
        if m2:
            n = m2.group(1)
            base_tpl = url.replace(f"000{n}_1.m3u8", "000{n}_1.m3u8")
            template_map["fmt2"] = base_tpl
            continue
        # 匹配格式3 /hls/{n}/index.m3u8
        m3 = FORMAT3_PATTERN.search(url)
        if m3:
            n = m3.group(1)
            base_tpl = re.sub(r"/hls/\d{1,2}/index\.m3u8", r"/hls/{n}/index.m3u8", url)
            template_map["fmt3"] = base_tpl
            continue
    # 根据提取到的模板生成完整CCTV1-17补全链接
    # fmt1 cctv{n}.m3u8 n=1~17 → CCTVn
    if "fmt1" in template_map:
        tpl = template_map["fmt1"]
        for num in range(1, 18):
            url = tpl.format(n=num)
            ch_name = f"CCTV{num}"
            complement_list.append(ChannelItem(
                extinf=f'#EXTINF:-1,{ch_name}',
                url=url,
                name=ch_name,
                cctv_digit=str(num)
            ))
    # fmt2 000{n}_1.m3u8 n=1~17 → CCTVn
    if "fmt2" in template_map:
        tpl = template_map["fmt2"]
        for num in range(1, 18):
            url = tpl.format(n=f"{num:02d}")
            ch_name = f"CCTV{num}"
            complement_list.append(ChannelItem(
                extinf=f'#EXTINF:-1,{ch_name}',
                url=url,
                name=ch_name,
                cctv_digit=str(num)
            ))
    # fmt3 /hls/{n}/index.m3u8 n1-18，n6=CCTV5+，n>6对应CCTV(n-1)
    if "fmt3" in template_map:
        tpl = template_map["fmt3"]
        for raw_n in range(1, 19):
            url = tpl.format(n=raw_n)
            if raw_n == 6:
                ch_name = "CCTV5+"
                digit = None
            elif raw_n < 6:
                ch_name = f"CCTV{raw_n}"
                digit = str(raw_n)
            else: # raw_n >=7 → CCTV(raw_n-1)
                real_n = raw_n - 1
                ch_name = f"CCTV{real_n}"
                digit = str(real_n)
            complement_list.append(ChannelItem(
                extinf=f'#EXTINF:-1,{ch_name}',
                url=url,
                name=ch_name,
                cctv_digit=digit
            ))
    print(f"✅ 从第一轮sou.txt提取模板生成补全CCTV链接：{len(complement_list)} 条")
    return complement_list

def main():
    all_channels: List[ChannelItem] = []
    seen_urls: Set[str] = set()
    # 步骤1：加载远程m3u源（含PHP动态m3u）
    source_urls = load_sources()
    print(f"加载 {len(source_urls)} 个远程源地址")
    for src in source_urls:
        channels = download_and_parse(src)
        print(f"解析 {src} 获取 {len(channels)} 条频道")
        for ch in channels:
            if ch.url not in seen_urls:
                seen_urls.add(ch.url)
                all_channels.append(ch)
    # 步骤2：自动生成CCTV规则探测链接，加入待测试列表
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
                print(f"❌ 链接失效或分辨率不足 ok={ok} height={height}")
    print(f"\n第一轮有效频道总数：{passed}")
    # 步骤4：第一次输出临时sou.txt
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            items = group_container[group_tag]
            if not items:
                continue
            if group_tag == "央视频道,#genre#":
                items = sort_cctv_group(items)
            for ch in items:
                f.write(f"{ch.name},{ch.url}\n")
    print(f"\n✅ 第一轮临时文件生成完成：{OUTPUT_FILE.name}")

    # ===================== 新增逻辑开始 =====================
    # 步骤5：从第一轮sou.txt提取三种CCTV链接模板，生成完整补全CCTV链接
    complement_cctv = generate_complement_cctv_from_sou()
    # 合并补全链接到待检测列表，自动去重
    for ch in complement_cctv:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            all_channels.append(ch)
    print(f"\n合并补全链接后总待检测频道：{len(all_channels)}")
    # 步骤6：二次并发校验新增的补全CCTV链接（仅校验新增，也可全量，这里复用现有流程统一校验）
    task_map2 = {}
    print(f"\n开始校验补全CCTV链接，并发线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for ch in complement_cctv:
            future = executor.submit(check_stream_valid, ch.url)
            task_map2[future] = ch
        finished2 = 0
        add_passed = 0
        for future in as_completed(task_map2):
            finished2 += 1
            ch = task_map2[future]
            try:
                ok, height = future.result()
            except Exception as e:
                print(f"[补全链接{finished2}/{len(complement_cctv)}] 任务异常 {ch.name}: {str(e)}")
                continue
            print(f"[补全链接{finished2}/{len(complement_cctv)}] {ch.name} | {ch.url[:70]}...")
            if ok and height >= MIN_HEIGHT:
                group_tag = classify_channel(ch)
                if group_tag is not None:
                    group_container[group_tag].append(ch)
                    add_passed += 1
                    print(f"✅ 补全链接通过 | {height}P | {group_tag.split(',#genre#')[0]}")
                else:
                    print(f"❌ 补全链接测速正常，无匹配分组，丢弃")
            else:
                print(f"❌ 补全链接失效或分辨率不足 ok={ok} height={height}")
    passed += add_passed
    print(f"\n补全链接新增有效频道：{add_passed}，最终总有效频道：{passed}")
    # ===================== 新增逻辑结束 =====================

    # 步骤7：覆盖写入最终完整sou.txt（包含原有+补全有效CCTV源）
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            items = group_container[group_tag]
            if not items:
                continue
            if group_tag == "央视频道,#genre#":
                items = sort_cctv_group(items)
            for ch in items:
                f.write(f"{ch.name},{ch.url}\n")
    print(f"\n✅ 最终完整文件生成完成：{OUTPUT_FILE.name}")
    print(f"在线地址：https://github.com/smxhlh/TV/blob/main/sou.txt")
if __name__ == "__main__":
    main()
