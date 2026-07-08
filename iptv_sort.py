import requests
import re
import os
from datetime import datetime

# ===================== 全局配置 =====================
# 目标m3u源地址
M3U_URL = "https://z.szyyds.cn/iptv"
# 输出分类文件
OUTPUT_CCTV = "cctv.txt"
OUTPUT_WEISHI = "weishi.txt"
OUTPUT_HENAN = "henan_local.txt"
OUTPUT_MOVIE = "movie.txt"
# 请求UA模拟浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}

# 分类匹配规则
# 央视：匹配任意CCTV+数字
CCTV_REG = re.compile(r"CCTV\d+", re.IGNORECASE)
# 卫视关键词
WEISHI_KEY = "卫视"
# 河南地方台完整名称列表
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法治", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园", "移动戏曲"
}
# 影视类关键词
MOVIE_KEYS = {
    "IPTV经典电影", "动作影院", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影"
}

# 分类存储容器
cctv_data = []
weishi_data = []
henan_data = []
movie_data = []
url_unique = set()  # 全局链接去重

# ===================== 工具函数 =====================
def fetch_m3u_source() -> str:
    """远程抓取m3u原始文本"""
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception as err:
        print(f"抓取源文件失败：{str(err)}")
        return ""

def parse_m3u(raw_text: str):
    """解析m3u文本，提取频道名+播放链接并分类"""
    lines = raw_text.splitlines()
    current_name = ""
    for line in lines:
        line = line.strip()
        # 提取频道名称 #EXTINF:-1,频道名称
        if line.startswith("#EXTINF") and "," in line:
            current_name = line.split(",", 1)[1].strip()
        # 匹配播放地址
        elif line.startswith(("http://", "https://")):
            play_url = line.strip()
            if not current_name or not play_url:
                continue
            # 链接去重
            if play_url in url_unique:
                continue
            url_unique.add(play_url)
            # 执行分类
            classify_channel(current_name, play_url)

def classify_channel(name: str, url: str):
    """频道分类，格式：频道名,#genre#,链接"""
    # 1.央视优先
    if CCTV_REG.search(name):
        cctv_data.append(f"{name},#CCTV#,{url}")
        return
    # 2.河南地方台
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            henan_data.append(f"{name},#HENAN#,{url}")
            return
    # 3.影视类
    for mv_word in MOVIE_KEYS:
        if mv_word in name:
            movie_data.append(f"{name},#MOVIE#,{url}")
            return
    # 4.卫视
    if WEISHI_KEY in name:
        weishi_data.append(f"{name},#WEISHI#,{url}")
        return
    # 不匹配四类直接丢弃

def save_category_file(file_path: str, data_list: list):
    """写入分类txt文件"""
    content = f"# 自动更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    content += "\n".join(data_list)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"生成文件 {file_path} | 频道总数：{len(data_list)}")

def main():
    print("===== M3U IPTV 自动分类工具（仅生成文件，无本地推送） =====")
    # 1.抓取源
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    # 2.解析分类
    parse_m3u(m3u_text)
    # 3.写入四类txt
    save_category_file(OUTPUT_CCTV, cctv_data)
    save_category_file(OUTPUT_WEISHI, weishi_data)
    save_category_file(OUTPUT_HENAN, henan_data)
    save_category_file(OUTPUT_MOVIE, movie_data)
    print("全部分类文件生成完成，等待GitHub Workflow提交推送")

if __name__ == "__main__":
    main()
