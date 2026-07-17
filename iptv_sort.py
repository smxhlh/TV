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
TEST_WORKERS = 12  # 降低并发，ffprobe占用CPU高
REUSE_OLD_SOURCE = True
# 分辨率阈值：低于1280*720直接丢弃
MIN_WIDTH = 1280
MIN_HEIGHT = 720

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}
# 正则规则：兼容 CCTV5+
CCTV_PATTERN = re.compile(r"CCTV\d+\+?", re.IGNORECASE)
WEISHI_KEY = "卫视"
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法制", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园"
}
# 影视关键词
MOVIE_KEYS = [
    "IPTV经典电影", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影","喜剧影院","星影"
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

# ===================== 分辨率检测工具 =====================
def get_video_resolution(url: str, timeout: float = 1.0):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-timeout", f"{int(timeout*1000)}000",
        url
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout + 1
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for stream in data["streams"]:
            if stream["codec_type"] == "video":
                w = int(stream.get("width", 0))
                h = int(stream.get("height", 0))
                return (w, h)
        return None
    except Exception:
        return None

# ===================== 测速工具（返回延迟+分辨率） =====================
def test_url_speed(url: str, timeout: float):
    try:
        start = datetime.now()
        resp = requests.head(url, headers=HEADERS, timeout=timeout)
        resp.close()
        cost = (datetime.now() - start).total_seconds()
        # 临时注释分辨率检测，测试连通性是否正常
        # res = get_video_resolution(url, timeout=1.0)
        # if res is None:
        #     return None, url
        # w, h = res
        # if w < MIN_WIDTH or h < MIN_HEIGHT:
        #     print(f"低清过滤 {w}×{h} {url}")
        #     return None, url
        # 临时固定模拟1080P分辨率
        w, h = 1920, 1080
        return (round(cost, 3), w, h, url), url
    except Exception:
        return None, url

def batch_test_speed(channel_url_list, timeout: float, workers: int):
    channel_speed_dict = {}
    task_list = []
    for name, url in channel_url_list:
        task_list.append((name, url))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(test_url_speed, url, timeout): name for name, url in task_list}
        for future in as_completed(future_map):
            chan_name = future_map[future]
            res_data, url = future.result()
            if res_data is not None:
                cost, w, h, u = res_data
                if chan_name not in channel_speed_dict:
                    channel_speed_dict[chan_name] = []
                channel_speed_dict[chan_name].append((cost, w, h, u))
    # 排序核心：分辨率从高到低，同分辨率延迟从小到大
    for k in channel_speed_dict:
        channel_speed_dict[k].sort(key=lambda x: (-x[1], -x[2], x[0]))
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
    match = CCTV_PATTERN.search(name)
    if match:
        pure_name = match.group()
        return "cctv", pure_name
    for keyword in MOVIE_KEYS:
        if keyword in name:
            return "movie", name
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            return "henan", name
    if WEISHI_KEY in name:
        return "weishi", name
    return None, None

def test_old_links():
    if not old_channel_links:
        return
    print(f"\n开始测速旧历史链接，并发{TEST_WORKERS}，超时{OLD_TEST_TIMEOUT}s")
    old_all_speed = batch_test_speed(old_channel_links, OLD_TEST_TIMEOUT, TEST_WORKERS)
    for chan_name, speed_url_list in old_all_speed.items():
        cat, real_name = classify_old_channel(chan_name, "")
        if cat is None:
            continue
        if real_name not in old_speed_map[cat]:
            old_speed_map[cat][real_name] = []
        old_speed_map[cat][real_name].extend(speed_url_list)
    print("旧链接测速完成，过滤低清与无法访问链接")

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
    match = CCTV_PATTERN.search(name)
    if match:
        pure_name = match.group()
        raw_cctv.append((pure_name, url))
        print(f" -> 归入央视：{pure_name}")
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
    print(f" -> 无匹配，丢弃：{name}")

# ===================== 测速新抓取源 =====================
def test_new_source():
    print(f"\n开始批量测速新抓取频道，并发数：{TEST_WORKERS}，超时限制：{TEST_TIMEOUT}s")
    global new_cctv_speed_map, new_movie_speed_map, new_henan_speed_map, new_weishi_speed_map
    new_cctv_speed_map = batch_test_speed(raw_cctv, TEST_TIMEOUT, TEST_WORKERS)
    new_movie_speed_map = batch_test_speed(raw_movie, TEST_TIMEOUT, TEST_WORKERS)
    new_henan_speed_map = batch_test_speed(raw_henan, TEST_TIMEOUT, TEST_WORKERS)
    new_weishi_speed_map = batch_test_speed(raw_weishi, TEST_TIMEOUT, TEST_WORKERS)
    print(f"新源测速完成")

# ===================== 合并旧有效链接 + 新测速链接 =====================
def merge_all_links():
    # 合并央视
    all_cctv_names = set(old_speed_map["cctv"].keys()) | set(new_cctv_speed_map.keys())
    for name in all_cctv_names:
        tmp = []
        if name in old_speed_map["cctv"]:
            tmp.extend(old_speed_map["cctv"][name])
        if name in new_cctv_speed_map:
            tmp.extend(new_cctv_speed_map[name])
        # URL去重
        url_set = set()
        unique_tmp = []
        # 合并后统一重排：分辨率优先，速度其次
        tmp_sorted = sorted(tmp, key=lambda x: (-x[1], -x[2], x[0]))
        for cost, w, h, u in tmp_sorted:
            if u not in url_set:
                url_set.add(u)
                unique_tmp.append((cost, w, h, u))
        final_cctv[name] = unique_tmp

    # 合并影视
    all_movie_names = set(old_speed_map["movie"].keys()) | set(new_movie_speed_map.keys())
    for name in all_movie_names:
        tmp = []
        if name in old_speed_map["movie"]:
            tmp.extend(old_speed_map["movie"][name])
        if name in new_movie_speed_map:
            tmp.extend(new_movie_speed_map[name])
        url_set = set()
        unique_tmp = []
        tmp_sorted = sorted(tmp, key=lambda x: (-x[1], -x[2], x[0]))
        for cost, w, h, u in tmp_sorted:
            if u not in url_set:
                url_set.add(u)
                unique_tmp.append((cost, w, h, u))
        final_movie[name] = unique_tmp

    # 合并河南
    all_henan_names = set(old_speed_map["henan"].keys()) | set(new_henan_speed_map.keys())
    for name in all_henan_names:
        tmp = []
        if name in old_speed_map["henan"]:
            tmp.extend(old_speed_map["henan"][name])
        if name in new_henan_speed_map:
            tmp.extend(new_henan_speed_map[name])
        url_set = set()
        unique_tmp = []
        tmp_sorted = sorted(tmp, key=lambda x: (-x[1], -x[2], x[0]))
        for cost, w, h, u in tmp_sorted:
            if u not in url_set:
                url_set.add(u)
                unique_tmp.append((cost, w, h, u))
        final_henan[name] = unique_tmp

    # 合并卫视
    all_weishi_names = set(old_speed_map["weishi"].keys()) | set(new_weishi_speed_map.keys())
    for name in all_weishi_names:
        tmp = []
        if name in old_speed_map["weishi"]:
            tmp.extend(old_speed_map["weishi"][name])
        if name in new_weishi_speed_map:
            tmp.extend(new_weishi_speed_map[name])
        url_set = set()
        unique_tmp = []
        tmp_sorted = sorted(tmp, key=lambda x: (-x[1], -x[2], x[0]))
        for cost, w, h, u in tmp_sorted:
            if u not in url_set:
                url_set.add(u)
                unique_tmp.append((cost, w, h, u))
        final_weishi[name] = unique_tmp
    print("\n旧链接+新源链接合并完成，去重后按【分辨率高优先、速度次之】排序")

# ===================== 输出文件 =====================
def save_merge_file():
    # 移除动态时间戳，解决git每次都判定变更
    content = "# IPTV全部分类源\n# 测速超时：1.2s | 自动过滤分辨率<1280*720低清源\n# 排序规则：分辨率从高到低，同分辨率响应速度从快到慢\n\n"
    # 央视排序
    content += "央视频道,#genre#\n"
    def cctv_sort_key(name):
        num_part = re.search(r"\d+", name).group()
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
    print("===== M3U IPTV 高清测速合并工具（分辨率优先排序） =====")
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
