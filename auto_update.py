import requests
import re
import time
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

# 关闭ssl警告
warnings.filterwarnings("ignore")

# ====================== 配置区 ======================
M3U_URL = "https://live.zbds.top/tv/iptv4.txt"
SAVE_FILE = "daily.txt"
TIMEOUT = 2.0
MAX_WORKERS = 22
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# 分支配置
CODE_BRANCH = "main"
DATA_BRANCH = "master"
# ====================================================

class IPTVSort:
    CCTV_PATTERN = re.compile(r"CCTV\-?(\d{1,2})\+?", re.IGNORECASE)
    MOVIE_KEYWORDS = {"电影", "影院"}
    HK_KEYWORDS = {"凤凰"}
    TV_KEYWORDS = {"卫视"}

def load_old_daily() -> list[tuple[str, str]]:
    """读取master分支拉取的旧daily.txt，返回[(名称,链接)]"""
    old_list = []
    if not os.path.exists(SAVE_FILE):
        print("未找到旧版daily.txt，无存量数据")
        return old_list
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
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
            if temp_name and url and url.startswith(("http://", "https://")):
                source_list.append((temp_name, url))
            temp_name = ""
    print(f"【步骤1完成】解析新源有效HTTP链接总数：{len(source_list)}")
    return source_list

def test_single_url(item):
    """测速，返回(名称,链接,耗时ms)，失效返回None"""
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
    print("【步骤2】启动多线程统一测速（新旧合并全部链接）……")
    total = len(source_list)
    finished_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        task_dict = {executor.submit(test_single_url, item): item for item in source_list}
        for task in as_completed(task_dict):
            finished_count += 1
            if finished_count % 100 == 0:
                print(f"测速进度 {finished_count}/{total}")
            data = task.result()
            if data:
                valid_result.append(data)
    # 按测速耗时升序，速度越快越靠前
    valid_result.sort(key=lambda x: x[2])
    print(f"【步骤2完成】测速完毕，可用播放源：{len(valid_result)}")
    # 去掉耗时，只保留频道名+链接
    return [(name, url) for name, url, _ in valid_result]

def merge_and_deduplicate(old_list, new_list):
    """合并新旧数据，按链接去重，保留第一次出现（测速更快的）"""
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

    # CCTV数字排序
    def sort_key(item):
        n = item[0].replace("CCTV", "").replace("+", "")
        return int(n) if n.isdigit() else 999
    cctv_list.sort(key=sort_key)
    return cctv_list, movie_list, hk_list, tv_list

def generate_output_txt(cctv, movie, hk, tv):
    # 覆盖前先清空旧文件
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
    print(f"【步骤3完成】文件 {SAVE_FILE} 生成成功！")

def main():
    start_time = time.time()
    # 1. 读取master分支存量旧数据
    old_data = load_old_daily()
    # 2. 获取新M3U源
    new_data = get_m3u_source()
    if not old_data and not new_data:
        print("无任何新旧播放源，程序退出")
        return
    # 3. 合并去重
    merged_all = merge_and_deduplicate(old_data, new_data)
    # 4. 全部统一测速+按速度排序
    valid_sorted = multi_thread_test(merged_all)
    # 5. 分类频道
    cctv_data, movie_data, hk_data, tv_data = classify_source(valid_sorted)
    # 6. 生成文件
    generate_output_txt(cctv_data, movie_data, hk_data, tv_data)
    cost = round(time.time() - start_time, 2)
    print(f"\n===== 全部任务执行完毕，总耗时：{cost} 秒 =====")

if __name__ == "__main__":
    main()
