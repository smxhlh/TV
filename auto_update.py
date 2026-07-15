import requests
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== 配置区 ==========
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
SAVE_FILE = "每日更新.txt"
TIMEOUT = 2.0        # 缩短超时
MAX_WORKERS = 25     # 并发线程数，不要超过30防止封禁
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
# ============================

class IPTVSort:
    CCTV_PATTERN = re.compile(r"CCTV-?(\d{1,2})", re.IGNORECASE)
    MOVIE_KEYWORDS = {"电影", "影院"}
    HK_KEYWORDS = {"凤凰"}
    TV_KEYWORDS = {"卫视"}


def get_m3u_source():
    print("开始下载M3U源...")
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        content = resp.text
    except Exception as e:
        print(f"下载失败：{str(e)}")
        return []

    source_list = []
    name = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            if "," in line:
                name = line.split(",")[-1].strip()
        elif line and not line.startswith("#"):
            url = line
            if name and url:
                source_list.append((name, url))
                name = ""
    print(f"解析完成，原始频道总数：{len(source_list)}")
    return source_list


def test_single_url(item):
    """单链接测速函数，给多线程调用"""
    name, url = item
    try:
        # 只使用HEAD探测，减少流量与耗时
        res = requests.head(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        if 200 <= res.status_code < 300:
            return (name, url)
    except Exception:
        pass
    return None


def multi_thread_test(source_list):
    """多线程并发测速"""
    valid = []
    print(f"启动并发测速，并发数：{MAX_WORKERS}")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        task_map = {executor.submit(test_single_url, item): item for item in source_list}
        finished = 0
        for task in as_completed(task_map):
            res = task.result()
            finished += 1
            if finished % 100 == 0:
                print(f"已测速 {finished}/{len(source_list)}")
            if res:
                valid.append(res)
    print(f"测速结束，有效源数量：{len(valid)}")
    return valid


def classify_source(valid_list):
    cctv_list = []
    movie_list = []
    hk_list = []
    tv_list = []

    for name, url in valid_list:
        match = IPTVSort.CCTV_PATTERN.search(name)
        if match:
            num_str = match.group(1)
            if num_str.isdigit():
                num = int(num_str)
                if 1 <= num <= 17:
                    # CCTV5 单独处理 CCTV5+
                    if "5+" in name:
                        std_name = "CCTV5+"
                    else:
                        std_name = f"CCTV{num}"
                    # 去重，同一个频道只保留第一个有效链接
                    exists = any(x[0] == std_name for x in cctv_list)
                    if not exists:
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

    # CCTV排序
    def cctv_sort_key(item):
        n = item[0].replace("CCTV", "").replace("+", "")
        return int(n) if n.isdigit() else 999
    cctv_list.sort(key=cctv_sort_key)
    return cctv_list, movie_list, hk_list, tv_list


def generate_txt(cctv, movie, hk, tv):
    content = []
    content.append("央视频道,#genre#")
    for name, url in cctv:
        content.append(f"{name},{url}")
    content.append("")

    content.append("电影频道,#genre#")
    for name, url in movie:
        content.append(f"{name},{url}")
    content.append("")

    content.append("香港频道,#genre#")
    for name, url in hk:
        content.append(f"{name},{url}")
    content.append("")

    content.append("卫视频道,#genre#")
    for name, url in tv:
        content.append(f"{name},{url}")

    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print(f"{SAVE_FILE} 生成完毕！")


def main():
    t_start = time.time()
    sources = get_m3u_source()
    if not sources:
        print("未获取到源，程序退出")
        return
    valid_sources = multi_thread_test(sources)
    cctv_data, movie_data, hk_data, tv_data = classify_source(valid_sources)
    generate_txt(cctv_data, movie_data, hk_data, tv_data)
    print(f"全部任务完成，总耗时：{round(time.time()-t_start,2)} 秒")


if __name__ == "__main__":
    main()
