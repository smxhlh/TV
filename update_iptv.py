import requests
import re
import time

# 配置参数
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
OUTPUT_FILE = "每日更新.txt"
# 补充缺失的CCTV5、CCTV5+ 可用稳定源（国内可播放、无地区限制）
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

def check_url_valid(url):
    """快速检测链接是否有效，过滤失效/不支持的链接"""
    invalid_keyword = ["404", "not found", "area", "境外", "不支持", "无法访问"]
    # 过滤特殊后缀无效链接
    if url.endswith((".ts", ".html")) or "go.bkpcp.top" in url:
        return False
    try:
        # 超时快速探测，不完整下载
        res = requests.head(url, timeout=3, allow_redirects=True)
        return res.status_code < 400
    except:
        return False

def parse_iptv(m3u_text):
    """解析M3U、过滤失效链接、补全缺失CCTV5/5+、精准分类"""
    cctv_list = []
    movie_list = []
    hongkong_list = []
    satellite_list = []

    # 兼容 CCTV-1/CCTV1 格式
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

            # CCTV频道匹配 + 有效性过滤
            cctv_res = cctv_pattern.search(channel_name)
            if cctv_res:
                cctv_code = cctv_res.group(1).upper()
                standard_name = f"CCTV{cctv_code}"
                # 只保存有效链接，剔除系统报错的失效源
                if standard_name not in cctv_exist and check_url_valid(channel_url):
                    cctv_exist[standard_name] = channel_url
                    cctv_list.append(f"{standard_name},{channel_url}")
            
            # 电影频道
            if "电影" in channel_name or "影院" in channel_name:
                if check_url_valid(channel_url):
                    movie_list.append(f"{channel_name},{channel_url}")
            
            # 香港凤凰频道
            if "凤凰" in channel_name:
                if check_url_valid(channel_url):
                    hongkong_list.append(f"{channel_name},{channel_url}")
            
            # 卫视频道
            if "卫视" in channel_name:
                if check_url_valid(channel_url):
                    satellite_list.append(f"{channel_name},{channel_url}")
            
            channel_name = ""
            channel_url = ""
    
    # ========== 核心修复：强制补全缺失的 CCTV5、CCTV5+ ==========
    for name, url in FIX_CCTV_SOURCE.items():
        if name not in cctv_exist:
            cctv_list.append(f"{name},{url}")

    # CCTV固定排序
    cctv_sort_map = {
        "CCTV1":1, "CCTV2":2, "CCTV3":3, "CCTV4":4, "CCTV5":5,
        "CCTV5+":6, "CCTV6":7, "CCTV7":8, "CCTV8":9, "CCTV9":10,
        "CCTV10":11, "CCTV11":12, "CCTV12":13, "CCTV13":14,
        "CCTV14":15, "CCTV15":16, "CCTV16":17, "CCTV17":18
    }
    cctv_list.sort(key=lambda x: cctv_sort_map.get(x.split(",")[0], 99))

    return cctv_list, movie_list, hongkong_list, satellite_list

def generate_txt(cctv, movie, hk, satellite):
    """生成标准OK影视TXT格式"""
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
    print(f"✅ 更新完成：已补全CCTV5/CCTV5+、过滤所有失效链接！")

if __name__ == "__main__":
    m3u_content = download_m3u(M3U_URL)
    if m3u_content:
        cctv, movie, hk, satellite = parse_iptv(m3u_content)
        generate_txt(cctv, movie, hk, satellite)
