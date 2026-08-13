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
# CCTV数字范围 1~17
CCTV_NUM_RANGE = range(1, 18)
CCTV_VALID_NUMBERS = set(str(i) for i in CCTV_NUM_RANGE)
# CCTV自动探测生成模板（4种主流路径）
CCTV_GENERATE_TEMPLATES = [
    ("http://127.0.0.1/live/cctv{n}.m3u8", "CCTV{n}"),
    ("http://127.0.0.1/live/cctv{n}hd.m3u8", "CCTV{n} HD"),
    ("http://127.0.0.1/tsfile/live/000{n:02d}_1.m3u8", "CCTV{n}"),
    ("http://127.0.0.1/hls/{n}/index.m3u8", "CCTV{n}")
]

# ====================== 频道匹配正则（修复完整版） ======================
# 匹配名称CCTV1~17、CCTV5+
RULE_CCTV = re.compile(r"CCTV-?\s*(?:([1-9]|1[0-7])\+?)", re.IGNORECASE)
# 电影频道含“影”
RULE_MOVIE = re.compile(r"影")
# 河南频道
RULE_HENAN = re.compile(r"河南")
# 卫视频道
RULE_WEISHI = re.compile(r"卫视")
# 过滤区间无效名称 CCTV1-CCTV10 这类
LOW_CCTV_FILTER = re.compile(r"CCTV-?\s*(\d{1,2})\s*-\s*CCTV-?\s*(\d{1,2})", re.IGNORECASE)
# 提取CCTV编号，支持 数字+ 适配CCTV5+，限制1-17
CCTV_NUM_EXTRACT = re.compile(r"CCTV-?\s*((?:[1-9]|1[0-7])(?:\+)?)", re.IGNORECASE)
# 标准化CCTV名称，兼容高清/HD/体育后缀
REG_CCTV_STD = re.compile(
    r"CCTV-?\s*((?:[1-9]|1[0-7])\+?).*?(体育|高清|HD|-体育)",
    re.IGNORECASE
)
# 过滤标清SD源
REG_SD_FILTER = re.compile(r"标清|SD", re.IGNORECASE)
# 单独IP匹配
REG_PROXY_IP = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
# IP+端口匹配
REG_IP_PORT = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)")

# 四种CCTV m3u8链接格式（新增偏移编号兼容）
FORMAT1_PATTERN = re.compile(r"/live/cctv([1-9]|1[0-7])(hd)?\.m3u8", re.IGNORECASE)
FORMAT2_PATTERN = re.compile(r"/tsfile/live/(000|10)(0[1-9]|1[0-7])_1\.m3u8", re.IGNORECASE)
FORMAT3_PATTERN = re.compile(r"/hls/(30)?([1-9]|1[0-7])/index\.m3u8", re.IGNORECASE)
FORMAT4_PATTERN = re.compile(r"cctv([1-9]|1[0-7])hd\.m3u8", re.IGNORECASE)

# CCTV直播URL全局匹配规则（移除$尾锚，新增偏移路径，兼容任意参数）
CCTV_URL_PATTERNS = [
    r"/live/cctv(?:[1-9]|1[0-7])(hd)?\.m3u8(\?.*)?",
    r"/tsfile/live/000(?:0[1-9]|1[0-7])_1\.m3u8(\?.*)?",
    r"/tsfile/live/10(?:0[1-9]|1[0-7])_1\.m3u8(\?.*)?",
    r"/hls/(?:[1-9]|1[0-7])/index\.m3u8(\?.*)?",
    r"/hls/30(?:0[1-9]|1[0-7])/index\.m3u8(\?.*)?",
    r"cctv(?:[1-9]|1[0-7])hd\.m3u8(\?.*)?"
]

# 匹配CCTV前缀
REGEX_CCTV_PREFIX = re.compile(r"CCTV-?", re.IGNORECASE)
# 只提取纯数字，用于排序（不含+）
REGEX_CCTV_NUM = re.compile(r"CCTV-?\s*((?:[1-9]|1[0-7]))", re.IGNORECASE)

# 【修改】新增其他频道分组，输出顺序：央视、电影、卫视、河南、其他
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

def generate_cctv_probe_channels() -> List[ChannelItem]:
    """自动生成CCTV1~17探测频道（内置HD模板）"""
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

def parse_m3u(raw_text: str) -> List[ChannelItem]:
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
    """修复测速误判：识别无服务/区域限制报错，只有正常解析出分辨率才算有效"""
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
        err_lower = stderr.lower()
        # 识别两类业务报错：无服务、区域不可用 + 通用HTTP错误
        invalid_err_keywords = [
            "no server configured",
            "content is not available in your area",
            "403 forbidden",
            "404 not found",
            "connection refused",
            "unable to open resource"
        ]
        # 命中限制类报错直接判定失效
        for kw in invalid_err_keywords:
            if kw in err_lower:
                print(f"[源限制报错] {url} : {kw}")
                return False, None
        # 仅当成功捕获宽高分辨率才视为有效流
        res_match = re.search(r"(\d+)x(\d+)", stderr)
        if res_match:
            height = int(res_match.group(2))
            return True, height
        # 无分辨率信息 = 无有效视频流
        return False, None
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
        print(f"[测速超时] {url}")
        return False, None
    except Exception as e:
        if proc:
            try:
                proc.kill()
            except:
                pass
        print(f"[测速异常] {url} : {str(e)}")
        return False, None

# 【修改】分类函数：匹配不到四类自动归入其他频道，不再返回None
def classify_channel(item: ChannelItem) -> str:
    name = item.name
    url = item.url
    match_cctv_url = False
    # 使用re.search全局匹配URL中的路径片段，不再限制开头
    for pattern in CCTV_URL_PATTERNS:
        if re.search(pattern, url):
            match_cctv_url = True
            break
    # 央视优先
    if match_cctv_url or REGEX_CCTV_PREFIX.search(name):
        return "央视频道,#genre#"
    # 电影频道
    if "影" in name:
        return "电影频道,#genre#"
    # 卫视频道
    if "卫视" in name:
        return "卫视频道,#genre#"
    # 河南频道（排除河南卫视，卫视走上面分支）
    if "河南" in name and "河南卫视" not in name:
        return "河南频道,#genre#"
    # 所有不匹配的统一归入其他频道
    return "其他频道,#genre#"

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

def deduplicate_channel_list(channels: List[ChannelItem]) -> List[ChannelItem]:
    """频道列表按URL全局去重，解决输出重复行"""
    seen = set()
    res = []
    for ch in channels:
        if ch.url not in seen:
            seen.add(ch.url)
            res.append(ch)
    return res

# 从临时文件提取4种CCTV模板批量补全链接
def generate_complement_cctv_from_sou() -> List[ChannelItem]:
    complement_list = []
    if not OUTPUT_FILE.exists():
        return complement_list
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        sou_lines = [line.strip() for line in f.readlines() if line.strip() and "," in line]
    template_map: Dict[str, str] = {}
    for line in sou_lines:
        name, url = line.split(",", maxsplit=1)
        m1 = FORMAT1_PATTERN.search(url)
        if m1:
            n = m1.group(1)
            base_tpl = url.replace(f"cctv{n}.m3u8", "cctv{n}.m3u8")
            template_map["fmt1"] = base_tpl
            continue
        m2 = FORMAT2_PATTERN.search(url)
        if m2:
            n = m2.group(2)
            base_tpl = url.replace(f"{m2.group(1)}{n}_1.m3u8", "{pre}{n:02d}_1.m3u8")
            template_map["fmt2"] = base_tpl
            continue
        m3 = FORMAT3_PATTERN.search(url)
        if m3:
            base_tpl = re.sub(r"/hls/(30)?\d{1,2}/index\.m3u8", r"/hls/{pre}{n}/index.m3u8", url)
            template_map["fmt3"] = base_tpl
            continue
        m4 = FORMAT4_PATTERN.search(url)
        if m4:
            n = m4.group(1)
            base_tpl = url.replace(f"cctv{n}hd.m3u8", "cctv{n}hd.m3u8")
            template_map["fmt4"] = base_tpl
            continue
    # fmt1 cctv{n}.m3u8
    if "fmt1" in template_map:
        tpl = template_map["fmt1"]
        for num in range(1, 18):
            url = tpl.format(n=num)
            ch_name = f"CCTV{num}"
            complement_list.append(ChannelItem(f'#EXTINF:-1,{ch_name}', url, ch_name, str(num)))
    # fmt2 000{n}_1.m3u8 / 10{n}_1.m3u8
    if "fmt2" in template_map:
        tpl = template_map["fmt2"]
        for num in range(1, 18):
            url = tpl.format(pre="000", n=f"{num:02d}")
            ch_name = f"CCTV{num}"
            complement_list.append(ChannelItem(f'#EXTINF:-1,{ch_name}', url, ch_name, str(num)))
    # fmt3 /hls/{n}/index.m3u8 / hls/30{n}
    if "fmt3" in template_map:
        tpl = template_map["fmt3"]
        for raw_n in range(1, 19):
            url = tpl.format(pre="", n=raw_n)
            if raw_n == 6:
                ch_name = "CCTV5+"
                digit = None
            elif raw_n < 6:
                ch_name = f"CCTV{raw_n}"
                digit = str(raw_n)
            else:
                real_n = raw_n - 1
                ch_name = f"CCTV{real_n}"
                digit = str(real_n)
            complement_list.append(ChannelItem(f'#EXTINF:-1,{ch_name}', url, ch_name, digit))
    # fmt4 cctv{n}hd.m3u8 HD模板
    if "fmt4" in template_map:
        tpl = template_map["fmt4"]
        for num in range(1, 18):
            url = tpl.format(n=num)
            ch_name = f"CCTV{num}"
            complement_list.append(ChannelItem(f'#EXTINF:-1,{ch_name}', url, ch_name, str(num)))
    print(f"✅ 从第一轮sou.txt提取模板生成补全CCTV链接：{len(complement_list)} 条")
    return complement_list

def main():
    all_channels: List[ChannelItem] = []
    seen_urls: Set[str] = set()
    # 步骤1 加载远程源
    source_urls = load_sources()
    print(f"加载 {len(source_urls)} 个远程源地址")
    for src in source_urls:
        channels = download_and_parse(src)
        print(f"解析 {src} 获取 {len(channels)} 条频道")
        for ch in channels:
            if ch.url not in seen_urls:
                seen_urls.add(ch.url)
                all_channels.append(ch)
    # 步骤2 生成内置探测频道（含HD模板）
    probe_channels = generate_cctv_probe_channels()
    for ch in probe_channels:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            all_channels.append(ch)
    print(f"去重后待检测频道总数：{len(all_channels)}")

    # 【修改】删除名称过滤丢弃逻辑，全部频道进入测速
    valid_name_channels = all_channels
    print(f"\n全部{len(valid_name_channels)}条频道进入测速（无丢弃，统一自动分类）")

    # 第一轮并发测速
    group_container: Dict[str, List[ChannelItem]] = {g: [] for g in GROUP_ORDER}
    passed = 0
    task_map = {}
    print(f"\n开始并发测速，并发线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for ch in valid_name_channels:
            future = executor.submit(check_stream_valid, ch.url)
            task_map[future] = ch
        finished = 0
        for future in as_completed(task_map):
            finished += 1
            ch = task_map[future]
            try:
                ok, height = future.result()
            except Exception as e:
                print(f"[{finished}/{len(valid_name_channels)}] 任务异常 {ch.name}: {str(e)}")
                continue
            print(f"[{finished}/{len(valid_name_channels)}] {ch.name} | {ch.url[:70]}...")
            if ok and height >= MIN_HEIGHT:
                group_tag = classify_channel(ch)
                group_container[group_tag].append(ch)
                passed += 1
                print(f"✅ 通过 | {height}P | {group_tag.split(',#genre#')[0]}")
            else:
                print(f"❌ 链接失效或分辨率不足 ok={ok} height={height}")
    print(f"\n第一轮有效频道总数：{passed}")
    # 临时输出第一轮结果（用于提取HD模板），每组先去重
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            items = group_container[group_tag]
            items = deduplicate_channel_list(items)
            if not items:
                continue
            if group_tag == "央视频道,#genre#":
                items = sort_cctv_group(items)
            for ch in items:
                f.write(f"{ch.name},{ch.url}\n")
    print(f"\n✅ 第一轮临时文件生成完成：{OUTPUT_FILE.name}")
    # 提取模板生成补全链接
    complement_cctv = generate_complement_cctv_from_sou()
    # 合并补全链接，全局去重
    new_complement = []
    for ch in complement_cctv:
        if ch.url not in seen_urls:
            seen_urls.add(ch.url)
            new_complement.append(ch)
    complement_cctv = new_complement
    print(f"\n合并去重后补全待检测频道：{len(complement_cctv)}")

    # 【修改】补全链接同样全部进入测速，无丢弃
    valid_complement_channels = complement_cctv
    print(f"补全链接共{len(valid_complement_channels)}条全部进入测速")

    # 二次测速补全HD等链接
    task_map2 = {}
    print(f"\n开始校验补全CCTV链接，并发线程数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for ch in valid_complement_channels:
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
                print(f"[补全链接{finished2}/{len(valid_complement_channels)}] 任务异常 {ch.name}: {str(e)}")
                continue
            print(f"[补全链接{finished2}/{len(valid_complement_channels)}] {ch.name} | {ch.url[:70]}...")
            if ok and height >= MIN_HEIGHT:
                group_tag = classify_channel(ch)
                group_container[group_tag].append(ch)
                add_passed += 1
                print(f"✅ 补全链接通过 | {height}P | {group_tag.split(',#genre#')[0]}")
            else:
                print(f"❌ 补全链接失效或分辨率不足 ok={ok} height={height}")
    passed += add_passed
    print(f"\n补全链接新增有效频道：{add_passed}，最终总有效频道：{passed}")
    # 最终写入前每组强制URL去重，彻底解决重复行
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for group_tag in GROUP_ORDER:
            raw_items = group_container[group_tag]
            unique_items = deduplicate_channel_list(raw_items)
            if not unique_items:
                continue
            if group_tag == "央视频道,#genre#":
                unique_items = sort_cctv_group(unique_items)
            for ch in unique_items:
                f.write(f"{ch.name},{ch.url}\n")
    print(f"\n✅ 最终完整文件生成完成：{OUTPUT_FILE.name}")
    print(f"在线地址：https://github.com/smxhlh/TV/blob/main/sou.txt")

if __name__ == "__main__":
    main()
