import requests
import re

# 配置参数
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
OUTPUT_FILE = "每日更新.txt"

def download_m3u(url):
    """下载远程M3U源文件"""
    try:
        resp = requests.get(url, timeout=15)
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"下载源文件失败：{e}")
        return ""

def parse_iptv(m3u_text):
    """解析M3U内容并分类筛选"""
    # 定义分类存储列表
    cctv_list = []
    movie_list = []
    hongkong_list = []
    satellite_list = []

    # CCTV正则：匹配CCTV1-CCTV17、CCTV5+，忽略中文后缀
    cctv_pattern = re.compile(r"CCTV(5\+|[1-9]|1[0-7])", re.IGNORECASE)
    # 初始化已匹配的CCTV编号，去重
    cctv_exist = set()

    # 逐行解析M3U内容，提取频道名称
    lines = m3u_text.splitlines()
    channel_name = ""

    for line in lines:
        line = line.strip()
        # 提取频道名称行
        if line.startswith("#EXTINF"):
            # 匹配频道名称
            name_match = re.search(r",(.+)$", line)
            if name_match:
                channel_name = name_match.group(1).strip()
        # 频道播放地址行，代表单条频道结束，开始分类
        elif line and not line.startswith("#") and channel_name:
            # 1. 央视频道筛选 CCTV1-17、CCTV5+
            cctv_res = cctv_pattern.search(channel_name)
            if cctv_res:
                cctv_code = cctv_res.group(1).upper()
                standard_name = f"CCTV{cctv_code}"
                if standard_name not in cctv_exist:
                    cctv_exist.add(standard_name)
                    cctv_list.append(standard_name + ",")
            
            # 2. 电影频道（含电影、影院关键字）
            if "电影" in channel_name or "影院" in channel_name:
                movie_list.append(channel_name + ",")
            
            # 3. 香港频道（含凤凰关键字）
            if "凤凰" in channel_name:
                hongkong_list.append(channel_name + ",")
            
            # 4. 卫视频道（含卫视关键字）
            if "卫视" in channel_name:
                satellite_list.append(channel_name + ",")
            
            # 重置临时频道名
            channel_name = ""
    
    # 对CCTV频道排序（规范顺序CCTV1-CCTV17、CCTV5+）
    cctv_sort_map = {
        "CCTV1":1, "CCTV2":2, "CCTV3":3, "CCTV4":4, "CCTV5":5,
        "CCTV5+":6, "CCTV6":7, "CCTV7":8, "CCTV8":9, "CCTV9":10,
        "CCTV10":11, "CCTV11":12, "CCTV12":13, "CCTV13":14,
        "CCTV14":15, "CCTV15":16, "CCTV16":17, "CCTV17":18
    }
    cctv_list.sort(key=lambda x: cctv_sort_map.get(x.replace(",",""), 99))

    return cctv_list, movie_list, hongkong_list, satellite_list

def generate_txt(cctv, movie, hk, satellite):
    """生成OK影视格式的TXT文件"""
    content = []
    # 央视频道分区
    content.append("央视频道,#genre#")
    content.extend(cctv)
    content.append("")
    # 电影频道分区
    content.append("电影频道,#genre#")
    content.extend(movie)
    content.append("")
    # 香港频道分区
    content.append("香港频道,#genre#")
    content.extend(hk)
    content.append("")
    # 卫视频道分区
    content.append("卫视频道,#genre#")
    content.extend(satellite)

    # 写入文件
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    print(f"文件 {OUTPUT_FILE} 生成成功！")

if __name__ == "__main__":
    m3u_content = download_m3u(M3U_URL)
    if m3u_content:
        cctv, movie, hk, satellite = parse_iptv(m3u_content)
        generate_txt(cctv, movie, hk, satellite)
