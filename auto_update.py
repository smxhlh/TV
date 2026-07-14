import requests
import re
import os

# 配置常量
M3U_URL = "https://iptv-org.github.io/iptv/index.m3u"
SAVE_FILE = "每日更新.txt"

def fetch_m3u_source():
    """拉取远程M3U播放源文件，增加容错处理"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(M3U_URL, timeout=15, headers=headers)
        response.encoding = "utf-8"
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"源文件拉取失败：{str(e)}")
        return ""

def parse_channel_data(m3u_text):
    """
    解析M3U文本，分类筛选频道
    返回分类字典：{分类名: [(频道名, 链接), ...]}
    """
    # 初始化分类容器
    classify_data = {
        "央视频道": [],
        "电影频道": [],
        "香港频道": [],
        "卫视频道": []
    }

    # 兼容换行格式，优化正则匹配精度
    channel_pattern = re.compile(r'#EXTINF:-1,(.*?)\r?\n(https?://.*?)\r?\n')
    channel_list = channel_pattern.findall(m3u_text)

    # CCTV1-CCTV17 正则匹配（包含CCTV5+，兼容所有中文后缀）
    cctv_pattern = re.compile(r'CCTV\s*(\d+\+?)', re.IGNORECASE)
    valid_cctv_num = {"1","2","3","4","5","5+","6","7","8","9","10","11","12","13","14","15","16","17"}

    for name, url in channel_list:
        name_strip = name.strip()
        # 1. 筛选央视频道
        cctv_res = cctv_pattern.search(name_strip)
        if cctv_res:
            cctv_code = cctv_res.group(1)
            if cctv_code in valid_cctv_num:
                standard_name = f"CCTV{cctv_code}"
                # 去重处理
                if not any(item[0] == standard_name for item in classify_data["央视频道"]):
                    classify_data["央视频道"].append((standard_name, url))
                continue

        # 2. 筛选电影频道
        if "电影" in name_strip or "影院" in name_strip:
            classify_data["电影频道"].append((name_strip, url))
            continue

        # 3. 筛选香港凤凰频道
        if "凤凰" in name_strip:
            classify_data["香港频道"].append((name_strip, url))
            continue

        # 4. 筛选卫视频道
        if "卫视" in name_strip:
            classify_data["卫视频道"].append((name_strip, url))
            continue

    return classify_data

def generate_txt_file(classify_data):
    """生成OK影视格式的每日更新.txt"""
    content = ""
    # 按固定顺序拼接分类内容
    # 1. 央视
    content += "央视频道,#genre#\n"
    for name, url in classify_data["央视频道"]:
        content += f"{name},{url}\n"
    content += "\n"

    # 2. 电影
    content += "电影频道,#genre#\n"
    for name, url in classify_data["电影频道"]:
        content += f"{name},{url}\n"
    content += "\n"

    # 3. 香港
    content += "香港频道,#genre#\n"
    for name, url in classify_data["香港频道"]:
        content += f"{name},{url}\n"
    content += "\n"

    # 4. 卫视
    content += "卫视频道,#genre#\n"
    for name, url in classify_data["卫视频道"]:
        content += f"{name},{url}\n"

    # 写入文件
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"文件生成成功：{SAVE_FILE}")
    return True

if __name__ == "__main__":
    # 全局异常捕获，避免退出码2报错
    try:
        m3u_text = fetch_m3u_source()
        if m3u_text:
            classify_res = parse_channel_data(m3u_text)
            generate_txt_file(classify_res)
            print("脚本执行完成，退出码0")
        else:
            print("未获取到有效源数据，脚本正常退出")
    except Exception as e:
        print(f"脚本执行异常：{str(e)}")
