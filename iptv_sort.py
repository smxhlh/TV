import requests
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===================== 全局配置 =====================
M3U_URL = "https://z.szyyds.cn/iptv"
OUTPUT_ALL = "iptv_all.txt"
# 测速配置
TEST_TIMEOUT = 1.2
TEST_WORKERS = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}

# 正则规则：兼容 CCTV5+
CCTV_PATTERN = re.compile(r"CCTV\d+\+?", re.IGNORECASE)
WEISHI_KEY = "卫视"
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法治", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园", "移动戏曲"
}
# 新增喜剧影院，保留相声小品
MOVIE_KEYS = {
    "IPTV经典电影", "动作影院", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影", "喜剧影院"
}

# 原始存储（未测速）
raw_cctv = []
raw_henan = []
raw_weishi = []
raw_movie = []
url_unique = set()

# 测速后存储
cctv_speed_map = {}
movie_speed_map = {}
henan_speed_map = {}
weishi_speed_map = {}

# ===================== 测速工具 =====================
def test_url_speed(url: str):
    try:
        start = datetime.now()
        resp = requests.head(url, headers=HEADERS, timeout=TEST_TIMEOUT)
        resp.close()
        cost = (datetime.now() - start).total_seconds()
        return round(cost, 3), url
    except Exception:
        return None, url

def batch_test_speed(channel_url_list):
    channel_speed_dict = {}
    task_list = []
    for name, url in channel_url_list:
        task_list.append((name, url))

    with ThreadPoolExecutor(max_workers=TEST_WORKERS) as executor:
        future_map = {executor.submit(test_url_speed, url): name for name, url in task_list}
        for future in as_completed(future_map):
            chan_name = future_map[future]
            cost, url = future.result()
            if cost is not None:
                if chan_name not in channel_speed_dict:
                    channel_speed_dict[chan_name] = []
                channel_speed_dict[chan_name].append((cost, url))
    # 同频道按速度升序
    for k in channel_speed_dict:
        channel_speed_dict[k].sort(key=lambda x: x[0])
    return channel_speed_dict

# ===================== 抓取解析 =====================
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
    # 匹配CCTV5、CCTV5+这类格式
    match = CCTV_PATTERN.search(name)
    if match:
        pure_name = match.group()
        raw_cctv.append((pure_name, url))
        return
    # 影视匹配
    for mv_word in MOVIE_KEYS:
        if mv_word in name:
            raw_movie.append((name, url))
            return
    # 河南台
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            raw_henan.append((name, url))
            return
    # 卫视
    if WEISHI_KEY in name:
        raw_weishi.append((name, url))

# ===================== 测速处理 =====================
def process_all_data():
    print(f"开始批量测速，并发数：{TEST_WORKERS}，超时限制：{TEST_TIMEOUT}s")
    global cctv_speed_map, movie_speed_map, henan_speed_map, weishi_speed_map
    cctv_speed_map = batch_test_speed(raw_cctv)
    movie_speed_map = batch_test_speed(raw_movie)
    henan_speed_map = batch_test_speed(raw_henan)
    weishi_speed_map = batch_test_speed(raw_weishi)

# ===================== 输出文件 =====================
def save_merge_file():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = f"# IPTV全部分类源 更新时间：{now}\n# 测速超时阈值：{TEST_TIMEOUT}s，同频道内链接按响应速度从快到慢排序\n\n"

    # 央视：兼容CCTV5+排序
    content += "央视频道,#genre#\n"
    # 自定义排序规则，先数字，再处理+号
    def cctv_sort_key(name):
        num_part = re.search(r"\d+", name).group()
        has_plus = 1 if "+" in name else 0
        return int(num_part), has_plus

    sorted_cctv_names = sorted(cctv_speed_map.keys(), key=cctv_sort_key)
    for cctv_name in sorted_cctv_names:
        for cost, url in cctv_speed_map[cctv_name]:
            content += f"{cctv_name},{url}\n"
    content += "\n"

    # 影视
    content += "影视,#genre#\n"
    sorted_movie_names = sorted(movie_speed_map.keys())
    for name in sorted_movie_names:
        for cost, url in movie_speed_map[name]:
            content += f"{name},{url}\n"
    content += "\n"

    # 河南
    content += "河南频道,#genre#\n"
    sorted_henan_names = sorted(henan_speed_map.keys())
    for name in sorted_henan_names:
        for cost, url in henan_speed_map[name]:
            content += f"{name},{url}\n"
    content += "\n"

    # 卫视
    content += "卫视频道,#genre#\n"
    sorted_weishi_names = sorted(weishi_speed_map.keys())
    for name in sorted_weishi_names:
        for cost, url in weishi_speed_map[name]:
            content += f"{name},{url}\n"

    with open(OUTPUT_ALL, "w", encoding="utf-8") as f:
        f.write(content)

    total_cctv_chan = len(cctv_speed_map)
    total_cctv_link = sum(len(v) for v in cctv_speed_map.values())
    total_movie_link = sum(len(v) for v in movie_speed_map.values())
    total_henan_link = sum(len(v) for v in henan_speed_map.values())
    total_weishi_link = sum(len(v) for v in weishi_speed_map.values())

    print(f"文件生成完成：{OUTPUT_ALL}")
    print(f"CCTV频道数：{total_cctv_chan} 有效CCTV链接：{total_cctv_link}")
    print(f"影视有效链接：{total_movie_link} 河南有效链接：{total_henan_link} 卫视有效链接：{total_weishi_link}")

def main():
    print("===== M3U IPTV 全分类测速排序工具 =====")
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    print("开始解析M3U频道...")
    parse_m3u(m3u_text)
    print(f"待测速总链接：CCTV:{len(raw_cctv)} 影视:{len(raw_movie)} 河南:{len(raw_henan)} 卫视:{len(raw_weishi)}")
    process_all_data()
    save_merge_file()
    print("文件生成完毕，等待Workflow提交推送")

if __name__ == "__main__":
    main()
