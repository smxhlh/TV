import requests
import re
import time
from typing import List, Tuple

# 配置常量
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
SAVE_FILE = "每日更新.txt"
# 测速超时时间（秒）
TIMEOUT = 3
# 请求请求头模拟浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 分类规则定义
class IPTVSort:
    # 央视频道：匹配CCTV1-CCTV17、CCTV5+，忽略后缀文字
    CCTV_PATTERN = re.compile(r"CCTV(?:-|\+)?(\d{1,2})", re.IGNORECASE)
    # 电影频道：含电影、影院关键字
    MOVIE_KEYWORDS = {"电影", "影院"}
    # 香港频道：含凤凰关键字
    HK_KEYWORDS = {"凤凰"}
    # 卫视频道：含卫视关键字
    TV_KEYWORDS = {"卫视"}

def get_m3u_source() -> List[Tuple[str, str]]:
    """
    下载并解析M3U文件，返回(频道名称,播放链接)列表
    """
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=10)
        resp.encoding = "utf-8"
        content = resp.text
    except Exception as e:
        print(f"下载M3U源失败：{str(e)}")
        return []

    # 解析m3u格式 #EXTINF:-1 ,频道名 \n 链接
    source_list = []
    name = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF"):
            # 提取频道名称
            if "," in line:
                name = line.split(",")[-1].strip()
        elif line and not line.startswith("#"):
            # 有效播放链接
            url = line
            if name and url:
                source_list.append((name, url))
                name = ""
    print(f"解析完成，共获取原始源：{len(source_list)} 个")
    return source_list

def test_url(url: str) -> bool:
    """
    测速：检测链接是否可播放
    """
    try:
        res = requests.head(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        if 200 <= res.status_code < 300:
            return True
        # HEAD请求失败则尝试GET
        res_get = requests.get(url, timeout=TIMEOUT, headers=HEADERS, stream=True)
        return 200 <= res_get.status_code < 300
    except:
        return False

def filter_valid_source(source_list: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """过滤无效链接，仅保留可播放源"""
    valid_list = []
    for name, url in source_list:
        if test_url(url):
            valid_list.append((name, url))
    print(f"测速完成，有效播放源：{len(valid_list)} 个")
    return valid_list

def classify_source(valid_list: List[Tuple[str, str]]):
    """
    按规则分类频道
    返回：央视、电影、香港、卫视 四类列表
    """
    cctv_list = []
    movie_list = []
    hk_list = []
    tv_list = []

    for name, url in valid_list:
        # 1. 匹配央视频道 CCTV1-17、CCTV5+
        cctv_match = IPTVSort.CCTV_PATTERN.search(name)
        if cctv_match:
            num = cctv_match.group(1)
            # 限定1-17频道
            if num.isdigit() and 1 <= int(num) <= 17:
                # 统一规范命名，忽略后缀多余文字
                if "+" in name or num == "5":
                    std_name = f"CCTV{num}+" if num == "5" else f"CCTV{num}"
                else:
                    std_name = f"CCTV{num}"
                # 去重添加
                if not any(x[0] == std_name for x in cctv_list):
                    cctv_list.append((std_name, url))
            continue

        # 2. 电影频道
        if any(k in name for k in IPTVSort.MOVIE_KEYWORDS):
            movie_list.append((name, url))
            continue

        # 3. 香港凤凰频道
        if any(k in name for k in IPTVSort.HK_KEYWORDS):
            hk_list.append((name, url))
            continue

        # 4. 卫视频道
        if any(k in name for k in IPTVSort.TV_KEYWORDS):
            tv_list.append((name, url))
            continue

    # 央视频道按数字排序
    cctv_list.sort(key=lambda x: int(x[0].replace("CCTV","").replace("+","")))
    return cctv_list, movie_list, hk_list, tv_list

def generate_txt(cctv, movie, hk, tv):
    """生成标准格式每日更新.txt"""
    content = []
    # 央视频道
    content.append("央视频道,#genre#")
    for name, url in cctv:
        content.append(f"{name},{url}")
    content.append("")

    # 电影频道
    content.append("电影频道,#genre#")
    for name, url in movie:
        content.append(f"{name},{url}")
    content.append("")

    # 香港频道
    content.append("香港频道,#genre#")
    for name, url in hk:
        content.append(f"{name},{url}")
    content.append("")

    # 卫视频道
    content.append("卫视频道,#genre#")
    for name, url in tv:
        content.append(f"{name},{url}")

    # 写入文件
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print(f"文件生成完成：{SAVE_FILE}")

def main():
    # 1. 采集解析源
    source_data = get_m3u_source()
    if not source_data:
        return
    # 2. 测速过滤
    valid_data = filter_valid_source(source_data)
    # 3. 分类整理
    cctv_data, movie_data, hk_data, tv_data = classify_source(valid_data)
    # 4. 生成TXT文件
    generate_txt(cctv_data, movie_data, hk_data, tv_data)

if __name__ == "__main__":
    main()
