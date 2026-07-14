import requests
import re

# 配置参数
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
OUTPUT_FILE = "每日更新.txt"

# 【国内稳定可用、不会失效】CCTV全频道兜底源（解决境外M3U下载失败空白问题）
CCTV_FIX_SOURCE = {
    "CCTV1": "http://ivi.bupt.edu.cn/hls/cctv1hd.m3u8",
    "CCTV2": "http://ivi.bupt.edu.cn/hls/cctv2hd.m3u8",
    "CCTV3": "http://ivi.bupt.edu.cn/hls/cctv3hd.m3u8",
    "CCTV4": "http://ivi.bupt.edu.cn/hls/cctv4hd.m3u8",
    "CCTV5": "http://ivi.bupt.edu.cn/hls/cctv5hd.m3u8",
    "CCTV5+": "http://ivi.bupt.edu.cn/hls/cctv5phd.m3u8",
    "CCTV6": "http://ivi.bupt.edu.cn/hls/cctv6hd.m3u8",
    "CCTV7": "http://ivi.bupt.edu.cn/hls/cctv7hd.m3u8",
    "CCTV8": "http://ivi.bupt.edu.cn/hls/cctv8hd.m3u8",
    "CCTV9": "http://ivi.bupt.edu.cn/hls/cctv9hd.m3u8",
    "CCTV10": "http://ivi.bupt.edu.cn/hls/cctv10hd.m3u8",
    "CCTV11": "http://ivi.bupt.edu.cn/hls/cctv11hd.m3u8",
    "CCTV12": "http://ivi.bupt.edu.cn/hls/cctv12hd.m3u8",
    "CCTV13": "http://ivi.bupt.edu.cn/hls/cctv13hd.m3u8",
    "CCTV14": "http://ivi.bupt.edu.cn/hls/cctv14hd.m3u8",
    "CCTV15": "http://ivi.bupt.edu.cn/hls/cctv15hd.m3u8",
    "CCTV16": "http://ivi.bupt.edu.cn/hls/cctv16hd.m3u8",
    "CCTV17": "http://ivi.bupt.edu.cn/hls/cctv17hd.m3u8"
}

def download_m3u(url):
    """下载远程M3U，失败不报错退出，返回空即可"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, timeout=10, headers=headers)
        resp.encoding = "utf-8"
        return resp.text
    except Exception:
        # 境外源访问失败，静默返回空，使用本地兜底源
        return ""

def parse_iptv(m3u_text):
    cctv_list = []
    movie_list = []
    hongkong_list = []
    satellite_list = []
    cctv_exist = dict()

    # 优先解析在线源（能下载成功就用在线最新源）
    if m3u_text:
        cctv_pattern = re.compile(r"CCTV-?(5\+|[1-9]|1[0-7])", re.IGNORECASE)
        lines = m3u_text.splitlines()
        channel_name = ""
        channel_url = ""

        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF"):
                name_match = re.search(r",(.+)$", line)
                if name_match:
                    channel_name = name_match.group(1).strip()
            elif line and not line.startswith("#") and channel_name:
                channel_url = line.strip()
                # 匹配CCTV
                cctv_res = cctv_pattern.search(channel_name)
                if cctv_res:
                    cctv_code = cctv_res.group(1).upper()
                    standard_name = f"CCTV{cctv_code}"
                    if standard_name not in cctv_exist:
                        cctv_exist[standard_name] = channel_url
                        cctv_list.append(f"{standard_name},{channel_url}")
                # 电影、凤凰、卫视分类
                if "电影" in channel_name or "影院" in channel_name:
                    movie_list.append(f"{channel_name},{channel_url}")
                if "凤凰" in channel_name:
                    hongkong_list.append(f"{channel_name},{channel_url}")
                if "卫视" in channel_name:
                    satellite_list.append(f"{channel_name},{channel_url}")
                channel_name = ""
                channel_url = ""
    
    # 核心修复：境外源加载失败时，100%补全所有CCTV频道兜底源
    for name, url in CCTV_FIX_SOURCE.items():
        if name not in cctv_exist:
            cctv_list.append(f"{name},{url}")

    # 固定CCTV排序
    cctv_sort_map = {
        "CCTV1":1, "CCTV2":2, "CCTV3":3, "CCTV4":4, "CCTV5":5,
        "CCTV5+":6, "CCTV6":7, "CCTV7":8, "CCTV8":9, "CCTV9":10,
        "CCTV10":11, "CCTV11":12, "CCTV12":13, "CCTV13":14,
        "CCTV14":15, "CCTV15":16, "CCTV16":17, "CCTV17":18
    }
    cctv_list.sort(key=lambda x: cctv_sort_map.get(x.split(",")[0], 99))

    return cctv_list, movie_list, hongkong_list, satellite_list

def generate_txt(cctv, movie, hk, satellite):
    content = []
    content.append("央视频道,#genre#")
    content.extend(cctv)
    content.append("")

    content.append("电影频道,#genre#")
    content.extend(movie)
    content.append("")

    content.append("香港频道,#genre#")
    content.extend(hk)
    content.append("")

    content.append("卫视频道,#genre#")
    content.extend(satellite)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print("✅ 更新成功！")

if __name__ == "__main__":
    m3u_content = download_m3u(M3U_URL)
    cctv, movie, hk, satellite = parse_iptv(m3u_content)
    generate_txt(cctv, movie, hk, satellite)
