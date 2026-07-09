import requests
import re
from datetime import datetime

# ===================== 全局配置 =====================
M3U_URL = "https://z.szyyds.cn/iptv"
# 仅输出单个合并文件
OUTPUT_ALL = "iptv_all.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}

# 分类匹配规则
# 匹配CCTV+数字，提取纯CCTV编号
CCTV_PATTERN = re.compile(r"(CCTV\d+)", re.IGNORECASE)
WEISHI_KEY = "卫视"
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法治", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园", "移动戏曲"
}
MOVIE_KEYS = {
    "IPTV经典电影", "动作影院", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影"
}

# 分类存储容器
cctv_data = []
henan_data = []
weishi_data = []
movie_data = []
url_unique = set()

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
            classify_channel(current_name, play_url)

def classify_channel(name: str, url: str):
    """频道分类，仅保存频道+url"""
    # 1.央视优先
    if CCTV_REG.search(name):
        cctv_data.append(f"{name},{url}")
        return
    # 2.影视类
    for mv_word in MOVIE_KEYS:
        if mv_word in name:
            movie_data.append(f"{name},{url}")
            return
    # 3.河南地方台
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            henan_data.append(f"{name},{url}")
            return
    # 4.卫视
    if WEISHI_KEY in name:
        weishi_data.append(f"{name},{url}")
        return
    # 不匹配四类直接丢弃

def save_merge_file():
    """生成单一合并txt，顺序：央视 → 影视 → 河南地方 → 卫视"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = f"# IPTV全部分类源 更新时间：{now}\n\n"

    # 1.央视频道
    content += "央视频道,#genre#\n"
    content += "\n".join(cctv_data) + "\n\n"

    # 2.影视
    content += "影视,#genre#\n"
    content += "\n".join(movie_data) + "\n\n"

    # 3.河南频道
    content += "河南频道,#genre#\n"
    content += "\n".join(henan_data) + "\n\n"

    # 4.卫视频道
    content += "卫视频道,#genre#\n"
    content += "\n".join(weishi_data) + "\n"

    with open(OUTPUT_ALL, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"合并文件生成完成：{OUTPUT_ALL}")
    print(f"央视：{len(cctv_data)} 影视：{len(movie_data)} 河南：{len(henan_data)} 卫视：{len(weishi_data)}")

def main():
    print("===== M3U IPTV 单文件分类工具 =====")
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    parse_m3u(m3u_text)
    save_merge_file()
    print("文件生成完毕，等待Workflow提交推送")

if __name__ == "__main__":
    main()
