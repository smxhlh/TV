import requests
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

# 关闭ssl警告
warnings.filterwarnings("ignore")

# ====================== 配置区 ======================
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
SAVE_FILE = "daily.txt"
TIMEOUT = 2.0
MAX_WORKERS = 22  # GitHub Actions推荐20~25之间，防止触发限流
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# ====================================================

class IPTVSort:
    # 兼容 CCTV1 / CCTV-1 / CCTV5+ 各种写法
    CCTV_PATTERN = re.compile(r"CCTV\-?(\d{1,2})\+?", re.IGNORECASE)
    MOVIE_KEYWORDS = {"电影", "影院"}
    HK_KEYWORDS = {"凤凰"}
    TV_KEYWORDS = {"卫视"}


def get_m3u_source():
    print("【步骤1】开始下载M3U源文件...")
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=15, verify=False)
        resp.encoding = "utf-8"
        content = resp.text
    except Exception as e:
        print(f"下载M3U失败：{str(e)}")
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
            # 只保留http/https链接，过滤udp rtsp等无效链接
            if temp_name and url and url.startswith(("http://", "https://")):
                source_list.append((temp_name, url))
            temp_name = ""
    print(f"【步骤1完成】解析有效HTTP链接总数：{len(source_list)}")
    return source_list


def test_single_url(item):
    name, url = item
    try:
        res = requests.head(
            url,
            timeout=TIMEOUT,
            headers=HEADERS,
            allow_redirects=True,
            verify=False
        )
        if 200 <= res.status_code < 300:
            return (name, url)
    except Exception:
        pass
    return None


def multi_thread_test(source_list):
    valid_result = []
    print("【步骤2】启动多线程测速……")
    total = len(source_list)
    finished_count = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        task_dict = {executor.submit(test_single_url, item): item for item in source_list}
        for task in as_completed(task_dict):
            finished_count += 1
            # 每100条打印进度，方便观察是否卡死
            if finished_count % 100 == 0:
                print(f"测速进度 {finished_count}/{total}")
            data = task.result()
            if data:
                valid_result.append(data)

    print(f"【步骤2完成】测速完毕，可用播放源：{len(valid_result)}")
    return valid_result


def classify_source(valid_list):
    cctv_list = []
    movie_list = []
    hk_list = []
    tv_list = []
    # 用于CCTV去重集合
    cctv_exist = set()

    for name, url in valid_list:
        match = IPTVSort.CCTV_PATTERN.search(name)
        if match:
            num_str = match.group(1)
            if num_str.isdigit():
                num = int(num_str)
                if 1 <= num <= 17:
                    # 标准化频道名称，区分CCTV5+
                    if "5+" in name.upper():
                        std_name = "CCTV5+"
                    else:
                        std_name = f"CCTV{num}"

                    if std_name not in cctv_exist:
                        cctv_exist.add(std_name)
                        cctv_list.append((std_name, url))
            continue

        # 电影频道
        if any(k in name for k in IPTVSort.MOVIE_KEYWORDS):
            movie_list.append((name, url))
            continue
        # 香港凤凰频道
        if any(k in name for k in IPTVSort.HK_KEYWORDS):
            hk_list.append((name, url))
            continue
        # 卫视频道
        if any(k in name for k in IPTVSort.TV_KEYWORDS):
            tv_list.append((name, url))
            continue

    # CCTV 正确排序
    def sort_key(item):
        n = item[0].replace("CCTV", "").replace("+", "")
        return int(n) if n.isdigit() else 999
    cctv_list.sort(key=sort_key)

    return cctv_list, movie_list, hk_list, tv_list


def generate_output_txt(cctv, movie, hk, tv):
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
        lines.append("")

    lines.append("卫视频道,#genre#")
    for ch_name, ch_url in tv:
        lines.append(f"{ch_name},{ch_url}")

    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"【步骤3完成】文件 {SAVE_FILE} 生成成功！")


def main():
    start_time = time.time()
    source_data = get_m3u_source()
    if not source_data:
        print("未获取任何播放源，程序退出")
        return

    valid_data = multi_thread_test(source_data)
    cctv_data, movie_data, hk_data, tv_data = classify_source(valid_data)
    generate_output_txt(cctv_data, movie_data, hk_data, tv_data)

    cost = round(time.time() - start_time, 2)
    print(f"\n===== 全部任务执行完毕，总耗时：{cost} 秒 =====")


if __name__ == "__main__":
    main()
