import requests
import re
import os
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, timeout

# ===================== 全局配置 =====================
M3U_URL = "https://z.szyyds.cn/iptv"
OUTPUT_TXT = "IPTV.txt"
# 请求头模拟浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/150.0.0.0 Safari/537.36"
}
# 链接检测超时时间（秒）
CHECK_TIMEOUT = 6
# 并发检测线程数
CHECK_THREAD = 10

# 分类规则
# 央视正则：提取CCTV+数字，剔除后面文字
CCTV_REG = re.compile(r"(CCTV\d+)")
# 卫视标识
WEISHI_FLAG = "卫视"
# 河南本地台完整关键词
HENAN_CHANNELS = {
    "河南都市", "河南民生", "河南法治", "河南电视剧",
    "河南新闻", "河南公共", "河南梨园", "移动戏曲"
}
# 影视类关键词
MOVIE_KEYS = {
    "IPTV经典电影", "动作影院", "动作电影", "家庭影院",
    "电影", "相声小品", "经典电影"
}

# 存储待检测频道+链接
wait_check_list = []
# 存活有效线路
valid_channel_list = []
# 全局去重集合
url_unique_set = set()

# ===================== 工具函数 =====================
def fetch_m3u_source():
    """拉取m3u原始内容"""
    try:
        resp = requests.get(M3U_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text.strip()
    except Exception as e:
        print(f"源文件抓取失败: {str(e)}")
        return ""

def parse_m3u(raw_text):
    """解析m3u，筛选符合分类的频道，格式化CCTV名称"""
    lines = raw_text.splitlines()
    temp_name = ""
    for line in lines:
        line = line.strip()
        # 匹配频道名称行
        if line.startswith("#EXTINF") and "," in line:
            raw_name = line.split(",", 1)[1].strip()
            temp_name = raw_name
        # 匹配播放链接
        elif line.startswith(("http://", "https://")):
            link = line.strip()
            if not temp_name or not link:
                continue
            if link in url_unique_set:
                continue
            url_unique_set.add(link)

            final_name = filter_channel_name(temp_name)
            if final_name is None:
                continue
            wait_check_list.append((final_name, link))

def filter_channel_name(name: str):
    """频道分类过滤 + CCTV名称精简，不匹配四类则返回None丢弃"""
    # 1. 央视处理：提取CCTV数字，丢弃后缀文字
    cctv_match = CCTV_REG.search(name)
    if cctv_match:
        pure_cctv = cctv_match.group(1)
        return pure_cctv

    # 2. 河南本地台精确匹配
    for hn_name in HENAN_CHANNELS:
        if hn_name in name:
            return name

    # 3. 影视类匹配
    for movie_word in MOVIE_KEYS:
        if movie_word in name:
            return name

    # 4. 卫视匹配
    if WEISHI_FLAG in name:
        return name

    # 不属于四类，丢弃
    return None

def check_link_alive(args):
    """检测单条链接是否可访问"""
    ch_name, ch_url = args
    try:
        with timeout(CHECK_TIMEOUT):
            resp = requests.head(ch_url, headers=HEADERS, timeout=CHECK_TIMEOUT)
            if resp.status_code < 400:
                return (ch_name, ch_url)
    except Exception:
        pass
    return None

def batch_check_links():
    """多线程批量检测链接有效性"""
    print(f"开始批量检测 {len(wait_check_list)} 条线路存活状态...")
    with ThreadPoolExecutor(max_workers=CHECK_THREAD) as executor:
        results = executor.map(check_link_alive, wait_check_list)
    for res in results:
        if res is not None:
            valid_channel_list.append(f"{res[0]},{res[1]}")
    print(f"链接检测完成，有效线路：{len(valid_channel_list)} 条")

def save_single_txt():
    """输出单一IPTV.txt，OK影视标准格式"""
    now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"# 更新时间：{now_time}\n"
    content += "\n".join(valid_channel_list)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"已生成文件：{os.path.abspath(OUTPUT_TXT)}")

def git_auto_push():
    """自动Git提交推送（本地/Action通用）"""
    def safe_decode(data):
        if not data:
            return ""
        try:
            return data.decode("utf-8").strip()
        except:
            return data.decode("gbk", errors="ignore").strip()

    # 配置Git用户信息
    subprocess.run(["git", "config", "--global", "user.name", "AutoIPTVBot"], capture_output=True)
    subprocess.run(["git", "config", "--global", "user.email", "iptv@auto.com"], capture_output=True)

    # 拉取远端，冲突强制重置
    pull_cmd = subprocess.run(["git", "pull", "--rebase"], capture_output=True)
    if pull_cmd.returncode != 0:
        print("拉取仓库冲突，强制同步远端")
        subprocess.run(["git", "reset", "--hard", "origin/master"], capture_output=True)
        subprocess.run(["git", "clean", "-fd"], capture_output=True)

    # 添加、提交、推送
    subprocess.run(["git", "add", OUTPUT_TXT], capture_output=True)
    commit_msg = f"自动更新IPTV源 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    commit_res = subprocess.run(["git", "commit", "-m", commit_msg, "--allow-empty"], capture_output=True)
    if commit_res.returncode == 0:
        subprocess.run(["git", "push", "origin", "master"], capture_output=True)
        print("Git推送仓库成功")
    else:
        print("无内容变更，跳过推送")

def main():
    print("===== IPTV M3U 单文件分类+存活检测工具 =====")
    # 1. 抓取源
    m3u_text = fetch_m3u_source()
    if not m3u_text:
        print("源文件获取失败，程序退出")
        return
    # 2. 解析过滤频道
    parse_m3u(m3u_text)
    if not wait_check_list:
        print("无符合分类的频道，程序退出")
        return
    # 3. 批量检测链接有效性
    batch_check_links()
    if not valid_channel_list:
        print("所有线路全部失效，不生成文件")
        return
    # 4. 写入单一IPTV.txt
    save_single_txt()
    # 5. 自动推送Git仓库
    git_auto_push()

if __name__ == "__main__":
    main()
