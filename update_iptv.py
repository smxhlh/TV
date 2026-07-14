import requests
import re

# 配置参数
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
OUTPUT_FILE = "每日更新.txt"
# 固定稳定CCTV5、CCTV5+国内公益源（OK影视可直接播放）
FIX_CCTV_SOURCE = {
    "CCTV5": "http://ivi.bupt.edu.cn/hls/cctv5hd.m3u8",
    "CCTV5+": "http://ivi.bupt.edu.cn/hls/cctv5phd.m3u8"
}

def download_m3u(url):
    """下载远程M3U源文件"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, timeout=15, headers=headers)
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"下载源文件失败：{e}")
        return ""

def parse_iptv(m3u_text):
    """解析M3U、补全CCTV5/5+、精准分类、保留全部原生链接"""
    cctv_list = []
    movie_list = []
    hongkong_list = []
    satellite_list = []

    # 兼容 CCTV-1 / CCTV1 两种格式，匹配1-17、5+
    cctv_pattern = re.compile(r"CCTV-?(5\+|[1-9]|1[0-7])", re.IGNORECASE)
    cctv_exist = dict()

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

            # 匹配央视频道，标准化命名 + 去重
            cctv_res = cctv_pattern.search(channel_name)
            if cctv_res:
                cctv_code = cctv_res.group(1).upper()
                standard_name = f"CCTV{cctv_code}"
                if standard_name not in cctv_exist:
                    cctv_exist[standard_name] = channel_url
                    cctv_list.append(f"{standard_name},{channel_url}")
            
            # 电影频道分类
            if "电影" in channel_name or "影院" in channel_name:
                movie_list.append(f"{channel_name},{channel_url}")
            
            # 香港凤凰频道分类
            if "凤凰" in channel_name:
                hongkong_list.append(f"{channel_name},{channel_url}")
            
            # 卫视频道分类
            if "卫视" in channel_name:
                satellite_list.append(f"{channel_name},{channel_url}")
            
            # 重置临时变量
            channel_name = ""
            channel_url = ""
    
    # 强制补全缺失的 CCTV5 CCTV5+
    for name, url in FIX_CCTV_SOURCE.items():
        if name not in cctv_exist:
            cctv_list.append(f"{name},{url}")

    # 官方固定排序 CCTV1~17 + CCTV5+
    cctv_sort_map = {
        "CCTV1":1, "CCTV2":2, "CCTV3":3, "CCTV4":4, "CCTV5":5,
        "CCTV5+":6, "CCTV6":7, "CCTV7":8, "CCTV8":9, "CCTV9":10,
        "CCTV10":11, "CCTV11":12, "CCTV12":13, "CCTV13":14,
        "CCTV14":15, "CCTV15":16, "CCTV16":17, "CCTV17":18
    }
    cctv_list.sort(key=lambda x: cctv_sort_map.get(x.split(",")[0], 99))

    return cctv_list, movie_list, hongkong_list, satellite_list

def generate_txt(cctv, movie, hk, satellite):
    """生成OK影视标准TXT格式"""
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
    print("✅ IPTV源更新完成，无报错！")

if __name__ == "__main__":
    m3u_content = download_m3u(M3U_URL)
    if m3u_content:
        cctv, movie, hk, satellite = parse_iptv(m3u_content)
        generate_txt(cctv, movie, hk, satellite)
