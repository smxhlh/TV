import requests
import re
import os
from datetime import datetime

# ===================== 全局配置 =====================
M3U_URL = "https://z.szyyds.cn/iptv"
OUTPUT_CCTV = "cctv.txt"
OUTPUT_WEISHI = "weishi.txt"
OUTPUT_HENAN = "henan_local.txt"
OUTPUT_MOVIE = "movie.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}

# 分类规则
CCTV_REG = re.compile(r"CCTV\d+", re.IGNORECASE)
WEISHI_KEY = "卫视"
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法治", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园", "移动戏曲"
}
MOVIE_KEYS = {
    "IPTV经典电影", "动作影院", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影"
}

cctv_data = []
weishi_data = []
henan_data = []
movie_data = []
url_unique = set()

# ===================== 工具函数 =====================
def fetch_m3u_source() -> str:
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception as err:
        print(f"抓取源文件失败：{str(err)}")
        return ""

def parse_m3u(raw_text: str):
    lines = raw_text.splitlines()
    current_name = ""
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF") and "," in line:
            current_name = line.split(",", 1)[1].strip()
        elif line.startswith(("http://", "https://")):
            play_url = line.strip()
            if not current_name or not play_url:
                continue
            if play_url in url_unique:
                continue
            url_unique.add(play_url)
            classify_channel(current_name, play_url)

def classify_channel(name: str, url: str):
    if CCTV_REG.search(name):
        cctv_data.append(f"{name},#CCTV#,{url}")
        return
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            henan_data.append(f"{name},#HENAN#,{url}")
            return
    for mv_word in MOVIE_KEYS:
        if mv_word in name:
            movie_data.append(f"{name},#MOVIE#,{url}")
            return
    if WEISHI_KEY in name:
        weishi_data.append(f"{name},#WEISHI#,{url}")
        return

def save_category_file(file_path: str, data_list: list):
    content = f"# 自动更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += "\n".join(data_list)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"生成文件 {file_path} | 频道总数：{len(data_list)}")

def main():
    print("===== M3U IPTV 自动分类工具（仅生成文件） =====")
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    parse_m3u(m3u_text)
    save_category_file(OUTPUT_CCTV, cctv_data)
    save_category_file(OUTPUT_WEISHI, weishi_data)
    save_category_file(OUTPUT_HENAN, henan_data)
    save_category_file(OUTPUT_MOVIE, movie_data)
    print("全部分类文件生成完成，等待Workflow提交推送")

if __name__ == "__main__":
    main()
