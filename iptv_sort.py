import requests
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import subprocess
import json
# ===================== 全局配置 =====================
M3U_URL = "https://z.szyyds.cn/iptv"
OUTPUT_ALL = "iptv_all.txt"
# 测速配置
TEST_TIMEOUT = 1.2
OLD_TEST_TIMEOUT = 1.2
TEST_WORKERS = 12
REUSE_OLD_SOURCE = True
# 分辨率分层阈值
MIN_HD_WIDTH = 1280
MIN_HD_HEIGHT = 720
MIN_SD_WIDTH = 640
MIN_SD_HEIGHT = 480
# 单频道最多保留最优线路数量（补够5条）
MAX_SOURCE_PER_CHANNEL = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}
# CCTV标准化正则：匹配 4CCTV1、sCCTV-1、CCTV1综合、CCTV-1综合 等
# 捕获 CCTV数字(+?) 核心标识
CCTV_STD_PATTERN = re.compile(r".*(CCTV(\d+\+?)).*", re.IGNORECASE)
WEISHI_KEY = "卫视"
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法制", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园"
}
# 影视关键词
MOVIE_KEYS = [
    "IPTV经典电影", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影", "喜剧影院", "星影"
]
# 新抓取原始存储（未测速）
raw_cctv = []
raw_henan = []
raw_weishi = []
raw_movie = []
url_unique = set()
# 旧文件读取存储
old_channel_links = []  # [(name, url)]
old_speed_map = {
    "cctv": {},
    "henan": {},
    "weishi": {},
    "movie": {}
}
# 测速后存储（新源），元素 (cost, w, h, url)
new_cctv_speed_map = {}
new_movie_speed_map = {}
new_henan_speed_map = {}
new_weishi_speed_map = {}
# 最终合并结果
final_cctv = {}
final_movie = {}
final_henan = {}
final_weishi = {}

# ===================== 新增：CCTV名称标准化函数 =====================
def standardize_cctv_name(raw_name: str) -> str | None:
    """
    4CCTV1、sCCTV-1、4CCTV-1综合 → CCTV1
    CCTV5+、CCTV13 → 原样保留CCTV5+ / CCTV13
    不匹配返回None
    """
    match = CCTV_STD_PATTERN.search(raw_name)
    if not match:
        return None
    core = match.group(2)
    # 去掉中间横杠，统一格式 CCTV-1 → CCTV1
    core_clean = core.replace("-", "")
    return core_clean

# ===================== 分辨率检测工具【重构优化】 =====================
def get_video_resolution(url: str, timeout: float = 1.0):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-max_delay", "800000",       # 延长媒体缓冲等待
        "-flags", "low_delay",
        "-read_ahead_limit", "2048",
        "-timeout", f"{int(timeout*1000)}000",
        "-user_agent", HEADERS["User-Agent"],  # 携带UA防拦截
        url
    ]
    try:
        # ffprobe额外增加2秒容错超时
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 2
        )
        # 命令执行失败直接返回None
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for stream in data["streams"]:
            if stream["codec_type"] == "video":
                w = int(stream.get("width", 0))
                h = int(stream.get("height", 0))
                # 宽高为0无效流直接丢弃
                if w <= 0 or h <= 0:
                    return None
                # 低于480P直接丢弃
                if w < MIN_SD_WIDTH or h < MIN_SD_HEIGHT:
                    return None
                return (w, h)
        # 无视频轨道（纯音频）丢弃
        return None
    except Exception:
        return None

# ===================== 测速工具 =====================
def test_url_speed(url: str, timeout: float):
    try:
        start = datetime.now()
        # 开启自动重定向，兼容302直播源跳转
        resp = requests.head(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True
        )
        resp.close()
        # 校验HTTP状态码，非2xx直接判定失效
        if not (200 <= resp.status_code < 300):
            print(f"[失效] 异常状态码{resp.status_code} | {url}")
            return None
        cost = (datetime.now() - start).total_seconds()
        # 强制执行分辨率检测
        res = get_video_resolution(url, timeout=1.0)
        if res is None:
            print(f"[失效/过低清] ffprobe无法解析或分辨率不足480P | {url}")
            return None
        w, h = res
        print(f"[有效] 延迟{round(cost,3)}s {w}×{h} | {url}")
        return (round(cost, 3), w, h, url)
    except requests.exceptions.Timeout:
        print(f"[失效] 请求超时 | {url}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[失效] 无法连接服务器 | {url}")
        return None
    except requests.exceptions.SSLError:
        print(f"[失效] SSL证书异常 | {url}")
        return None
    except Exception as e:
        print(f"[失效] 未知异常 {str(e)} | {url}")
        return None

def batch_test_speed(channel_url_list, timeout: float, workers: int):
    channel_speed_dict = {}
    task_list = []
    for name, url in channel_url_list:
        task_list.append((name, url))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(test_url_speed, url, timeout): name for name, url in task_list}
        for future in as_completed(future_map):
            chan_name = future_map[future]
            res_data = future.result()
            # res_data为None代表失效/过低清，直接跳过不存入结果
            if res_data is not None:
                cost, w, h, u = res_data
                if chan_name not in channel_speed_dict:
                    channel_speed_dict[chan_name] = []
                channel_speed_dict[chan_name].append((cost, w, h, u))
    # 统一排序：高清在前，同清晰度延迟从小到大
    for k in channel_speed_dict:
        def sort_rule(item):
            cost, w, h, _ = item
            # 高清权重1，标清权重0，高清排前面；同权重延迟升序
            hd_flag = 1 if (w >= MIN_HD_WIDTH and h >= MIN_HD_HEIGHT) else 0
            return (-hd_flag, cost)
        channel_speed_dict[k].sort(key=sort_rule)
    return channel_speed_dict

# ===================== 读取旧文件链接 =====================
def load_old_links():
    if not os.path.exists(OUTPUT_ALL):
        print(f"本地旧文件 {OUTPUT_ALL} 不存在，跳过旧链接加载")
        return
    print(f"\n开始读取旧文件 {OUTPUT_ALL} 历史链接...")
    with open(OUTPUT_ALL, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        line = line.strip()
        if line.startswith("#") or line.endswith(",#genre#") or not line:
            continue
        if "," not in line:
            continue
        name, url = line.split(",", 1)
        name = name.strip()
        url = url.strip()
        if url.startswith("http"):
            old_channel_links.append((name, url))
    print(f"旧文件共读取 {len(old_channel_links)} 条历史链接")

def classify_old_channel(name: str, url: str):
    # CCTV标准化
    std_cctv = standardize_cctv_name(name)
    if std_cctv is not None:
        return "cctv", std_cctv
    for keyword in MOVIE_KEYS:
        if keyword in name:
            return "movie", name
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            return "henan", name
    if WEISHI_KEY in name:
        return "weishi", name
    return None, None

# ===================== 旧链接测速 =====================
def test_old_links():
    if not old_channel_links:
        return
    # 每次运行清空旧测速缓存
    old_speed_map["cctv"].clear()
    old_speed_map["henan"].clear()
    old_speed_map["weishi"].clear()
    old_speed_map["movie"].clear()
    print(f"\n开始测速旧历史链接，并发{TEST_WORKERS}，超时{OLD_TEST_TIMEOUT}s")
    old_all_speed = batch_test_speed(old_channel_links, OLD_TEST_TIMEOUT, TEST_WORKERS)
    for chan_name, speed_url_list in old_all_speed.items():
        cat, real_name = classify_old_channel(chan_name, "")
        if cat is None:
            continue
        if real_name not in old_speed_map[cat]:
            old_speed_map[cat][real_name] = []
        old_speed_map[cat][real_name].extend(speed_url_list)
    print("旧链接测速完成，当前有效历史源统计：")
    print(f"央视:{len(old_speed_map['cctv'])} 河南:{len(old_speed_map['henan'])} 卫视:{len(old_speed_map['weishi'])} 影视:{len(old_speed_map['movie'])}")

# ===================== 抓取解析新M3U源 =====================
def fetch_m3u_source() -> str:
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception as err:
        print(f"抓取源文件失败：{str(err)}")
        return ""

def parse_m3u(raw_text: str):
    lines = raw_text.splitlines()
    current_name = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF") and "," in line:
            current_name = line.split(",", 1)[1].strip()
        elif line.startswith(("http://", "https://")):
            play_url = line.strip()
            if not current_name or not play_url:
                continue
            if play_url in url_unique:
                continue
            url_unique.add(play_url)
            classify_channel(current_name, play_url)

def classify_channel(name: str, url: str):
    print(f"解析新频道：{name}")
    # CCTV标准化重命名
    std_cctv = standardize_cctv_name(name)
    if std_cctv is not None:
        raw_cctv.append((std_cctv, url))
        print(f" -> 归入央视标准化名称：{std_cctv}")
        return
    for keyword in MOVIE_KEYS:
        if keyword in name:
            raw_movie.append((name, url))
            print(f" -> 归入影视：{name} 匹配关键词：{keyword}")
            return
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            raw_henan.append((name, url))
            print(f" -> 归入河南：{name}")
            return
    if WEISHI_KEY in name:
        raw_weishi.append((name, url))
        print(f" -> 归入卫视：{name}")
        return
    print(f" -> 无匹配分类，丢弃：{name}")

# ===================== 测速新抓取源 =====================
def test_new_source():
    print(f"\n开始批量测速新抓取频道，并发数：{TEST_WORKERS}，超时限制：{TEST_TIMEOUT}s")
    global new_cctv_speed_map, new_movie_speed_map, new_henan_speed_map, new_weishi_speed_map
    new_cctv_speed_map = batch_test_speed(raw_cctv, TEST_TIMEOUT, TEST_WORKERS)
    new_movie_speed_map = batch_test_speed(raw_movie, TEST_TIMEOUT, TEST_WORKERS)
    new_henan_speed_map = batch_test_speed(raw_henan, TEST_TIMEOUT, TEST_WORKERS)
    new_weishi_speed_map = batch_test_speed(raw_weishi, TEST_TIMEOUT, TEST_WORKERS)
    print(f"新源测速完成")

# ===================== 合并旧有效链接 + 新测速链接【关键：高清优先，补标清凑5条】 =====================
def merge_channel_source(old_map, new_map, target_final):
    all_names = set(old_map.keys()) | set(new_map.keys())
    for name in all_names:
        tmp = []
        if name in old_map:
            tmp.extend(old_map[name])
        if name in new_map:
            tmp.extend(new_map[name])
        # URL去重
        url_set = set()
        unique_all = []
        # 先按高清在前、延迟升序排序
        def sort_rule(item):
            cost, w, h, _ = item
            hd_flag = 1 if (w >= MIN_HD_WIDTH and h >= MIN_HD_HEIGHT) else 0
            return (-hd_flag, cost)
        tmp_sorted = sorted(tmp, key=sort_rule)
        for cost, w, h, u in tmp_sorted:
            if u not in url_set:
                url_set.add(u)
                unique_all.append((cost, w, h, u))
        # 拆分高清组、标清组
        hd_list = []
        sd_list = []
        for item in unique_all:
            cost, w, h, u = item
            if w >= MIN_HD_WIDTH and h >= MIN_HD_HEIGHT:
                hd_list.append(item)
            else:
                sd_list.append(item)
        # 高清全部保留，不足MAX_SOURCE_PER_CHANNEL则补标清到5条
        final_list = hd_list.copy()
        need_fill = MAX_SOURCE_PER_CHANNEL - len(final_list)
        if need_fill > 0:
            final_list += sd_list[:need_fill]
        target_final[name] = final_list

def merge_all_links():
    # 合并四类频道
    merge_channel_source(old_speed_map["cctv"], new_cctv_speed_map, final_cctv)
    merge_channel_source(old_speed_map["henan"], new_henan_speed_map, final_henan)
    merge_channel_source(old_speed_map["weishi"], new_weishi_speed_map, final_weishi)
    merge_channel_source(old_speed_map["movie"], new_movie_speed_map, final_movie)
    print(f"\n旧链接+新源链接合并完成，高清源优先，不足{MAX_SOURCE_PER_CHANNEL}条自动补充480P标清源至{MAX_SOURCE_PER_CHANNEL}条，低于480P全部丢弃")

# ===================== 输出文件 =====================
def save_merge_file():
    content = "# IPTV全部分类源\n"
    content += f"# 高清阈值：{MIN_HD_WIDTH}×{MIN_HD_HEIGHT} | 兜底标清阈值：{MIN_SD_WIDTH}×{MIN_SD_HEIGHT}\n"
    content += f"# 规则：优先全部高清源，不足{MAX_SOURCE_PER_CHANNEL}条则补充480P标清源凑满{MAX_SOURCE_PER_CHANNEL}条；低于480P自动丢弃\n"
    content += "# CCTV频道自动标准化：4CCTV1/sCCTV-1综合 → CCTV1，CCTV5+保留加号格式\n\n"

    # 央视排序
    content += "央视频道,#genre#\n"
    def cctv_sort_key(name):
        match = re.search(r"\d+", name)
        num_part = match.group() if match else "999"
        has_plus = 1 if "+" in name else 0
        return int(num_part), has_plus
    sorted_cctv_names = sorted(final_cctv.keys(), key=cctv_sort_key)
    for cctv_name in sorted_cctv_names:
        for cost, w, h, url in final_cctv[cctv_name]:
            content += f"{cctv_name},{url}\n"
    content += "\n"
    # 影视
    content += "影视,#genre#\n"
    sorted_movie_names = sorted(final_movie.keys())
    for name in sorted_movie_names:
        for cost, w, h, url in final_movie[name]:
            content += f"{name},{url}\n"
    content += "\n"
    # 河南频道无数据则不输出区块
    if len(final_henan) > 0:
        content += "河南频道,#genre#\n"
        sorted_henan_names = sorted(final_henan.keys())
        for name in sorted_henan_names:
            for cost, w, h, url in final_henan[name]:
                content += f"{name},{url}\n"
        content += "\n"
    # 卫视
    content += "卫视频道,#genre#\n"
    sorted_weishi_names = sorted(final_weishi.keys())
    for name in sorted_weishi_names:
        for cost, w, h, url in final_weishi[name]:
            content += f"{name},{url}\n"
    with open(OUTPUT_ALL, "w", encoding="utf-8") as f:
        f.write(content)
    # 统计输出
    total_cctv_chan = len(final_cctv)
    total_cctv_link = sum(len(v) for v in final_cctv.values())
    total_movie_link = sum(len(v) for v in final_movie.values())
    total_henan_link = sum(len(v) for v in final_henan.values())
    total_weishi_link = sum(len(v) for v in final_weishi.values())
    print(f"\n文件生成完成：{OUTPUT_ALL}")
    print(f"CCTV频道数：{total_cctv_chan} 高清CCTV链接：{total_cctv_link}")
    print(f"影视高清链接：{total_movie_link} 河南高清链接：{total_henan_link} 卫视高清链接：{total_weishi_link}")

def main():
    is_ci = os.getenv("GITHUB_ACTIONS") is not None
    print("===== M3U IPTV 高清测速合并工具（CCTV标准化+480P兜底补源版） =====")
    print(f"当前运行环境：{'Github Actions CI' if is_ci else '本地电脑'}")
    if REUSE_OLD_SOURCE:
        load_old_links()
        test_old_links()
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    print("开始解析M3U新频道...")
    parse_m3u(m3u_text)
    print(f"\n新抓取待测速总链接：CCTV:{len(raw_cctv)} 影视:{len(raw_movie)} 河南:{len(raw_henan)} 卫视:{len(raw_weishi)}")
    test_new_source()
    merge_all_links()
    save_merge_file()
    print("文件生成完毕，等待Workflow提交推送")

if __name__ == "__main__":
    main()
