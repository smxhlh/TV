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

# ====================== 配置区 轻量化防OOM ======================
M3U_URL = "https://gh-proxy.com/raw.githubusercontent.com/vbskycn/iptv/refs/heads/master/tv/iptv4.txt"
SAVE_FILE = "daily.txt"
TIMEOUT = 3.0
FFMPEG_TIMEOUT = 4
FFPROBE_RETRY = 1
MAX_WORKERS_HTTP = 8
MAX_WORKERS_FF = 2
MIN_HEIGHT = 720

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# ====================================================

class IPTVSort:
    CCTV_PATTERN = re.compile(r"CCTV[\s\-]?(\d{1,2})\+?", re.IGNORECASE)
    MOVIE_KEYWORDS = {"电影", "影院", "影视", "CHC"}
    HK_KEYWORDS = {"凤凰", "香港"}
    TV_KEYWORDS = {"卫视", "电视台", "HD"}


def check_ffmpeg_exists():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        print("错误：未安装ffmpeg")
        return False


def get_stream_resolution(url: str):
    for _ in range(FFPROBE_RETRY + 1):
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
                time.sleep(0.3)
                continue
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    w = stream.get("width")
                    h = stream.get("height")
                    if w and h:
                        return (int(w), int(h))
            return None
        except Exception:
            time.sleep(0.3)
            continue
    return None


def load_old_daily() -> list[tuple[str, str]]:
    old_list = []
    if not os.path.exists(SAVE_FILE):
        print("未找到旧daily.txt")
        return old_list
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"读旧文件失败:{e}")
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
    print(f"读取存量频道：{len(old_list)}")
    return old_list


def get_m3u_source():
    print("【步骤1】下载源文件...")
    retry = 3
    content = ""
    while retry > 0:
        try:
            resp = requests.get(M3U_URL, headers=HEADERS, timeout=15, verify=False)
            resp.encoding = "utf-8"
            content = resp.text
            break
        except Exception as e:
            print(f"下载失败，剩余{retry}次:{e}")
            retry -= 1
            time.sleep(1)
    if not content:
        print("无源内容")
        return []
    source_list = []
    lines = content.splitlines()
    is_m3u = any(line.startswith("#EXTINF") for line in lines[:30])
    if is_m3u:
        temp_name = ""
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                temp_name = line.split(",")[-1].strip()
            elif line and not line.startswith("#"):
                url = line
                if temp_name and url.startswith(("http://", "https://")):
                    source_list.append((temp_name, url))
                    temp_name = ""
    else:
        for line in lines:
            line = line.strip()
            if not line or "#genre#" in line:
                continue
            if "," in line:
                name, url = line.split(",", 1)
                name = name.strip()
                url = url.strip()
                if url.startswith(("http://", "https://")):
                    source_list.append((name, url))
    print(f"解析新源总数：{len(source_list)}")
    return source_list


def test_single_url(item):
    name, url = item
    start = time.time()
    try:
        res = requests.get(
            url,
            timeout=TIMEOUT,
            headers=HEADERS,
            allow_redirects=True,
            verify=False,
            stream=True
        )
        data = b""
        for chunk in res.iter_content(chunk_size=1024):
            data += chunk
            if len(data) >= 4096:
                break
        cost_ms = round((time.time() - start) * 1000, 2)
        res.close()
        return (name, url, cost_ms)
    except Exception:
        return None


def multi_thread_http_test(source_list):
    print("【步骤2】HTTP连通测速")
    valid = []
    total = len(source_list)
    if total == 0:
        return []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_HTTP) as executor:
        tasks = [executor.submit(test_single_url, i) for i in source_list]
        idx = 0
        for fu in as_completed(tasks):
            idx += 1
            if idx % 80 == 0:
                print(f"测速进度 {idx}/{total}")
            ret = fu.result()
            if ret:
                valid.append(ret)
    # 修复语法错误：lambda x: x[2]
    valid.sort(key=lambda x: x[2])
    print(f"测速可用链接：{len(valid)}")
    return [(n, u) for n, u, _ in valid]


def filter_by_resolution(valid_links):
    print(f"【步骤3】分辨率检测（并发{MAX_WORKERS_FF}）总量{len(valid_links)}")
    qualified = []
    if not check_ffmpeg_exists():
        raise SystemExit(1)

    def ff_task(item):
        name, url = item
        time.sleep(0.4)
        res = get_stream_resolution(url)
        if res is None:
            return None
        w, h = res
        if h >= MIN_HEIGHT:
            return (name, url)
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_FF) as executor:
        tasks = [executor.submit(ff_task, i) for i in valid_links]
        idx = 0
        for fu in as_completed(tasks):
            idx += 1
            if idx % 15 == 0:
                print(f"分辨率检测 {idx}/{len(valid_links)}")
            ret = fu.result()
            if ret:
                qualified.append(ret)
    print(f"≥720P有效源：{len(qualified)}")
    return qualified


def merge_and_deduplicate(old_list, new_list):
    unique_map = {}
    # 旧源优先
    for n, u in old_list:
        if u not in unique_map:
            unique_map[u] = n
    for n, u in new_list:
        if u not in unique_map:
            unique_map[u] = n
    merged = [(v, k) for k, v in unique_map.items()]
    print(f"合并去重总数：{len(merged)}")
    return merged


def classify_source(valid_list):
    cctv_list = []
    movie_list = []
    hk_list = []
    tv_list = []
    cctv_exist = set()
    for name, url in valid_list:
        m = IPTVSort.CCTV_PATTERN.search(name)
        if m:
            num_str = m.group(1)
            if num_str.isdigit():
                num = int(num_str)
                if 1 <= num <= 17:
                    std = "CCTV5+" if "5+" in name.upper() else f"CCTV{num}"
                    if std not in cctv_exist:
                        cctv_exist.add(std)
                        cctv_list.append((std, url))
            continue
        if any(k in name for k in IPTVSort.MOVIE_KEYWORDS):
            movie_list.append((name, url))
            continue
        if any(k in IPTVSort.HK_KEYWORDS for k in name):
            hk_list.append((name, url))
            continue
        tv_list.append((name, url))

    def sort_key(x):
        s = x[0].replace("CCTV", "").replace("+", "")
        return int(s) if s.isdigit() else 999
    cctv_list.sort(key=sort_key)
    return cctv_list, movie_list, hk_list, tv_list


def generate_output_txt(cctv, movie, hk, tv):
    print("【步骤4】生成daily.txt")
    if os.path.exists(SAVE_FILE):
        os.remove(SAVE_FILE)
    lines = ["央视频道,#genre#"]
    lines.extend([f"{n},{u}" for n, u in cctv])
    lines.append("")
    lines.append("电影频道,#genre#")
    lines.extend([f"{n},{u}" for n, u in movie])
    lines.append("")
    lines.append("香港频道,#genre#")
    lines.extend([f"{n},{u}" for n, u in hk])
    lines.append("")
    lines.append("卫视频道,#genre#")
    lines.extend([f"{n},{u}" for n, u in tv])
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("文件生成完成")


def main():
    total_start = time.time()
    old = load_old_daily()
    new = get_m3u_source()
    if not old and not new:
        print("无任何源，退出")
        raise SystemExit(1)
    merged = merge_and_deduplicate(old, new)
    reach = multi_thread_http_test(merged)
    if not reach:
        print("无连通源，退出")
        raise SystemExit(1)
    hd_list = filter_by_resolution(reach)
    if not hd_list:
        print("无高清源，退出")
        raise SystemExit(1)
    c, m, h, t = classify_source(hd_list)
    generate_output_txt(c, m, h, t)
    print(f"全部完成，总耗时 {round(time.time() - total_start, 2)}s")


if __name__ == "__main__":
    main()
