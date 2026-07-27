import requests
import re
import time
import os
import warnings
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# 关闭ssl警告
warnings.filterwarnings("ignore")

# ====================== 配置区 ======================
M3U_URL = "https://live.zbds.top/tv/iptv4.txt"
SAVE_FILE = "daily.txt"
TIMEOUT = 2.0
# ffmpeg探测超时(秒)
FFMPEG_TIMEOUT = 4
MAX_WORKERS = 12
# 最低分辨率阈值 1280×720
MIN_WIDTH = 1280
MIN_HEIGHT = 720

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
CODE_BRANCH = "main"
DATA_BRANCH = "master"
# ====================================================

class IPTVSort:
    CCTV_PATTERN = re.compile(r"CCTV\-?(\d{1,2})\+?", re.IGNORECASE)
    MOVIE_KEYWORDS = {"电影", "影院"}
    HK_KEYWORDS = {"凤凰"}
    TV_KEYWORDS = {"卫视"}


def check_ffmpeg_exists():
    """检测环境是否有ffmpeg"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        print("错误：环境未安装ffmpeg，无法执行分辨率检测！")
        return False


def get_stream_resolution(url: str):
    """
    使用ffprobe获取视频流分辨率
    返回 (width, height)，失败返回 None
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-timeout", str(FFMPEG_TIMEOUT * 1000000),
        url
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = stream.get("width")
                h = stream.get("height")
                if w and h:
                    return (int(w), int(h))
        return None
    except Exception:
        return None


def load_old_daily() -> list[tuple[str, str]]:
    old_list = []
    if not os.path.exists(SAVE_FILE):
        print("未找到旧版daily.txt，无存量数据")
        return old_list
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"读取旧文件失败: {str(e)}")
        return old_list
    for line in lines:
        line = line.strip()
        if not line or "#genre#" in line:
            continue
        if "," in line:
            name, url = line.split(",", 1)
            name = name.strip()
            url = url.strip()
            if url.startswith(("http://", "https://")):
                old_list.append((name, url))
    print(f"读取存量频道总数：{len(old_list)}")
    return old_list


def get_m3u_source():
    print("【步骤1】开始下载M3U源文件...")
    retry = 3
    content = ""
    while retry > 0:
        try:
            resp = requests.get(M3U_URL, headers=HEADERS, timeout=10, verify=False)
            resp.encoding = "utf-8"
            content = resp.text
            break
        except Exception as e:
            retry -= 1
            print(f"下载M3U失败，剩余重试{retry}次：{str(e)}")
            time.sleep(1)
    if not content:
        print("多次重试下载M3U源失败，无新源数据")
        return []
    source_list = []
    temp_name = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            if "," in line:
                temp_name = line.split(",")[-1].strip()
        elif line and not line.startswith("#"):
            url = line
            if temp_name and url and url.startswith(("http://", "https://")):
                source_list.append((temp_name, url))
            temp_name = ""
    print(f"【步骤1完成】解析新源有效HTTP链接总数：{len(source_list)}")
    return source_list


def test_single_url(item):
    """基础连通测速，不通直接丢弃"""
    name, url = item
    start = time.time()
    try:
        res = requests.head(
            url,
            timeout=TIMEOUT,
            headers=HEADERS,
            allow_redirects=True,
            verify=False
        )
        cost_ms = round((time.time() - start) * 1000, 2)
        if 200 <= res.status_code < 300:
            return (name, url, cost_ms)
    except Exception:
        pass
    return None


def multi_thread_test(source_list):
    valid_result = []
    print("【步骤2】多线程连通测速，剔除无法访问链接……")
    total = len(source_list)
    finished_count = 0
    if total == 0:
        print("无待测速链接")
        return []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        task_dict = {executor.submit(test_single_url, item): item for item in source_list}
        for task in as_completed(task_dict):
            finished_count += 1
            if finished_count % 100 == 0:
                print(f"测速进度 {finished_count}/{total}")
            data = task.result()
            if data:
                valid_result.append(data)
    valid_result.sort(key=lambda x: x[2])
    print(f"【步骤2完成】连通可用链接：{len(valid_result)}")
    return [(name, url) for name, url, _ in valid_result]


def filter_by_resolution(valid_links):
    """
    FFmpeg分辨率过滤：只保留 ≥720P 视频流
    valid_links: [(name, url)]
    return: 符合清晰度的列表
    """
    print(f"【步骤3】开始FFmpeg分辨率检测，总量{len(valid_links)}……")
    qualified = []
    total = len(valid_links)
    cnt = 0
    ffmpeg_ok = check_ffmpeg_exists()
    if not ffmpeg_ok:
        print("ffmpeg不可用，终止程序")
        raise SystemExit(1)

    for name, url in valid_links:
        cnt += 1
        if cnt % 50 == 0:
            print(f"分辨率检测进度 {cnt}/{total}")
        res = get_stream_resolution(url)
        if res is None:
            # 无法获取流信息，丢弃
            continue
        w, h = res
        # 宽高任一达标即判定720P（兼容16:9/4:3）
        if w >= MIN_WIDTH and h >= MIN_HEIGHT:
            qualified.append((name, url))
    print(f"【步骤3完成】分辨率≥720P有效源：{len(qualified)}")
    return qualified


def merge_and_deduplicate(old_list, new_list):
    all_items = old_list + new_list
    unique_map = {}
    for name, url in all_items:
        if url not in unique_map:
            unique_map[url] = name
    merged = [(name, url) for url, name in unique_map.items()]
    print(f"新旧合并去重后总频道：{len(merged)}")
    return merged


def classify_source(valid_list):
    cctv_list = []
    movie_list = []
    hk_list = []
    tv_list = []
    cctv_exist = set()
    for name, url in valid_list:
        match = IPTVSort.CCTV_PATTERN.search(name)
        if match:
            num_str = match.group(1)
            if num_str.isdigit():
                num = int(num_str)
                if 1 <= num <= 17:
                    if "5+" in name.upper():
                        std_name = "CCTV5+"
                    else:
                        std_name = f"CCTV{num}"
                    if std_name not in cctv_exist:
                        cctv_exist.add(std_name)
                        cctv_list.append((std_name, url))
            continue
        if any(k in name for k in IPTVSort.MOVIE_KEYWORDS):
            movie_list.append((name, url))
            continue
        if any(k in name for k in IPTVSort.HK_KEYWORDS):
            hk_list.append((name, url))
            continue
        if any(k in name for k in IPTVSort.TV_KEYWORDS):
            tv_list.append((name, url))
            continue

    def sort_key(item):
        n = item[0].replace("CCTV", "").replace("+", "")
        return int(n) if n.isdigit() else 999
    cctv_list.sort(key=sort_key)
    return cctv_list, movie_list, hk_list, tv_list


def generate_output_txt(cctv, movie, hk, tv):
    try:
        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
        lines = []
        lines.append("央视频道,#genre#")
        for ch_name, ch_url in cctv:
            lines.append(f"{ch_name},{ch_url}")
        lines.append("")
        lines.append("电影频道,#genre#")
        for ch_name, ch_url in movie:
            lines.append(f"{ch_name},{ch_url}")
        lines.append("")
        lines.append("香港频道,#genre#")
        for ch_name, ch_url in hk:
            lines.append(f"{ch_name},{ch_url}")
        lines.append("")
        lines.append("卫视频道,#genre#")
        for ch_name, ch_url in tv:
            lines.append(f"{ch_name},{ch_url}")
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"【步骤4完成】文件 {SAVE_FILE} 生成成功！")
    except Exception as e:
        print(f"生成文件失败: {str(e)}")
        raise SystemExit(1)


def main():
    start_time = time.time()
    # 1. 读取旧源
    old_data = load_old_daily()
    # 2. 拉取新M3U
    new_data = get_m3u_source()
    if not old_data and not new_data:
        print("无任何新旧播放源，程序退出")
        raise SystemExit(1)
    # 3. 合并去重
    merged_all = merge_and_deduplicate(old_data, new_data)
    # 4. 连通测速，丢弃打不开链接
    reachable = multi_thread_test(merged_all)
    if not reachable:
        print("无任何可连通播放源，终止")
        raise SystemExit(1)
    # 5. FFmpeg过滤分辨率，低于720P全部丢弃
    hd_sources = filter_by_resolution(reachable)
    if not hd_sources:
        print("无分辨率≥720P有效频道，终止")
        raise SystemExit(1)
    # 6. 频道分类
    cctv_data, movie_data, hk_data, tv_data = classify_source(hd_sources)
    # 7. 写出txt
    generate_output_txt(cctv_data, movie_data, hk_data, tv_data)

    cost = round(time.time() - start_time, 2)
    print(f"\n===== 全部任务执行完毕，总耗时：{cost} 秒 =====")


if __name__ == "__main__":
    main()
