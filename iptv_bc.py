import re
import os
import time
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# ===================== 全局配置（CI云端适配 修复版） =====================
PROXY_URL = "http://tonkiang.us/iptvproxy.php"
CHANNEL_BASE = "http://tonkiang.us/channellist.html"
MAX_SAVE_GROUP = 3
# 加长等待适配CI网络
WAIT_TIME = 120
SLEEP_LONG = 8
SLEEP_SHORT = 3
RETRY_TIMES = 3
LOOP_WAIT_INTERVAL = 5
MAX_LOOP_WAIT = 20

# CI代理环境变量（Workflow注入 CI_HTTP_PROXY=http://xxx:port）
CI_PROXY = os.getenv("CI_HTTP_PROXY", "")
ENABLE_CI_PROXY = bool(CI_PROXY)

# CI环境：仓库根目录live.txt
LIVE_FILE_LOCAL = "live.txt"

# 失效关键字规则
INVALID_KEYWORDS = {
    "已经失效", "重新订阅", "欢迎来到", "提供订阅",
    "tonkiang.us", "系统内部异常", "end1",
    "这是一个境外网页", "当前无法访问"
}

# ===================== 工具函数 =====================
def log(step_desc):
    print(f"\n【{step_desc}】")
    print("-" * 60)

def safe_decode(data):
    if not data:
        return ""
    try:
        return data.decode("utf-8").strip()
    except:
        try:
            return data.decode("gbk").strip()
        except:
            return str(data)

# ===================== 文件读写 =====================
def load_live_json():
    default_data = {
        "lives": [],
        "update_seq": 0,
        "last_update": ""
    }
    if not os.path.exists(LIVE_FILE_LOCAL):
        save_live_json(default_data)
        return default_data
    try:
        with open(LIVE_FILE_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "update_seq" not in data:
            data["update_seq"] = 0
        if "last_update" not in data:
            data["last_update"] = ""
        if "lives" not in data or not isinstance(data["lives"], list):
            data["lives"] = []
        return data
    except (json.JSONDecodeError, Exception):
        return default_data

def save_live_json(data):
    data["update_seq"] += 1
    data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        with open(LIVE_FILE_LOCAL, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        if os.path.getsize(LIVE_FILE_LOCAL) == 0:
            print(" live.txt写入后为空")
            return False
        print(f"仓库根目录文件已更新，update_seq={data['update_seq']}")
        return True
    except Exception as e:
        print(f" 保存文件失败：{e}")
        return False

# ===================== 浏览器初始化（强化反爬+CI代理） =====================
def init_browser():
    chrome_options = Options()
    # CI标准无头模式
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-running-insecure-content")
    # 统一Windows UA，避免Linux无头UA被拦截
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # 关闭图片加载，提升页面渲染速度
    chrome_options.add_argument("--disable-images")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    # CI代理开启
    if ENABLE_CI_PROXY:
        chrome_options.add_argument(f"--proxy-server={CI_PROXY}")
        print(f"CI已启用代理：{CI_PROXY}")

    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2,
        "profile.managed_default_content_settings.images": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # 读取CI传入的chromedriver路径
    driver_path = os.getenv("CHROME_DRIVER_PATH")
    if driver_path and os.path.exists(driver_path):
        service = Service(executable_path=driver_path)
    else:
        service = Service()

    driver = webdriver.Chrome(service=service, options=chrome_options)
    # 双层隐藏webdriver爬虫特征
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh']});
        """
    })
    driver.set_page_load_timeout(WAIT_TIME)
    driver.set_script_timeout(WAIT_TIME)
    driver.implicitly_wait(WAIT_TIME)
    return driver

def safe_get(driver, url):
    for i in range(RETRY_TIMES + 1):
        try:
            driver.get(url)
            time.sleep(SLEEP_SHORT)
            return True
        except (TimeoutException, WebDriverException) as e:
            print(f"页面 {url} 加载失败，重试{i+1}，错误：{str(e)[:60]}")
            time.sleep(SLEEP_LONG)
    return False

# ===================== 链接检测 =====================
def check_url_alive(driver, url):
    if not url or not url.startswith(("http://", "https://")):
        print(" 链接为空/非有效网址，判定失效")
        return False
    try:
        if not safe_get(driver, url):
            print(" 页面加载超时，判定失效")
            return False
        page_text = driver.find_element("tag name", "body").text.strip()
        if len(page_text) < 5:
            print(" 页面内容为空，判定失效")
            return False
        for keyword in INVALID_KEYWORDS:
            if keyword in page_text:
                print(f" 命中失效关键字【{keyword}】，链接失效")
                return False
    except Exception as e:
        print(f" 链接检测异常: {str(e)[:40]}，判定失效")
        return False
    return True

# 页面正则提取函数（宽松兼容正则）
def wait_for_ip_tk(driver):
    loop_count = 0
    while loop_count < MAX_LOOP_WAIT:
        html = driver.page_source
        # 宽松正则：兼容空格、&amp;、换行、引号
        pattern = re.compile(
            r'ip\s*=\s*["\']?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})["\']?\s*[&;&amp;]\s*tk\s*=\s*["\']?([a-zA-Z0-9]+)["\']?',
            re.S
        )
        matches = pattern.findall(html)
        if matches:
            clean_matches = []
            seen = set()
            for ip, tk in matches:
                key = f"{ip}_{tk}"
                if key not in seen and ip and tk:
                    seen.add(key)
                    clean_matches.append((ip, tk))
            return clean_matches
        loop_count += 1
        print(f"等待IP/TK加载中 {loop_count}/{MAX_LOOP_WAIT}")
        time.sleep(LOOP_WAIT_INTERVAL)
    return []

def wait_for_token(driver):
    loop_count = 0
    while loop_count < MAX_LOOP_WAIT:
        html = driver.page_source
        pattern = re.compile(
            r"copytodr\s*\(\s*['\"](https://eastscreen\.tv/iptvlist\.php\?token=.+?)['\"]\s*,\s*['\"]t['\"]\s*\)",
            re.DOTALL
        )
        match = pattern.search(html)
        if match:
            return match.group(1)
        loop_count += 1
        time.sleep(LOOP_WAIT_INTERVAL)
    return None

# ===================== 主程序 =====================
def main():
    driver = None
    new_token_list = []
    try:
        print("========== CI云端IPTV采集脚本【修复版】 ==========")
        driver = init_browser()
        print("Linux无头Chrome启动成功")

        log("步骤1：读取仓库内 live.txt")
        live_data = load_live_json()
        live_list = live_data["lives"]
        print(f" 读取到 {len(live_list)} 条配置")
        exist_all_url = {item.get("url", "") for item in live_list if item.get("url")}
        need_replace_index = []

        log("步骤2：检测原有链接可用性")
        for idx, item in enumerate(live_list):
            item["name"] = f"直播{idx + 1}"
            old_url = item.get("url", "")
            if check_url_alive(driver, old_url):
                print(f" 第{idx+1}条正常，名称设为 直播{idx+1}")
            else:
                print(f" 第{idx+1}条失效，待替换")
                need_replace_index.append(idx)

        if not need_replace_index:
            print("\n 所有链接正常，无更新，直接退出")
            save_live_json(live_data)
            return

        need_replace_count = len(need_replace_index)
        log(f"步骤3：共有{need_replace_count}条失效线路，采集对应数量新IP/TK")

        if not safe_get(driver, PROXY_URL):
            print(" 主页面加载失败")
            return

        # 调试：打印页面前1000字符源码，判断是否被墙拦截
        page_html = driver.page_source[:1000]
        print(f"\n【调试页面源码片段】\n{page_html}\n")

        ip_tk_list = wait_for_ip_tk(driver)
        # 兜底：没拿到IP/TK则刷新页面重试一次
        if not ip_tk_list:
            print("首次未获取IP/TK，刷新页面重试一次")
            driver.refresh()
            time.sleep(SLEEP_LONG)
            ip_tk_list = wait_for_ip_tk(driver)

        if not ip_tk_list:
            print(" 未获取 IP/TK")
            return
        ip_tk_list = ip_tk_list[:10]

        log("步骤4：采集新播放链接（全局去重，凑够失效条数停止）")
        for idx, (ip, tk) in enumerate(ip_tk_list, 1):
            if len(new_token_list) >= need_replace_count:
                print(f" 已收集{need_replace_count}条新链接，满足替换需求，停止采集")
                break
            channel_url = f"{CHANNEL_BASE}?ip={ip}&tk={tk}&p=4"
            if safe_get(driver, channel_url):
                token_link = wait_for_token(driver)
                if token_link and token_link not in exist_all_url and token_link not in new_token_list:
                    new_token_list.append(token_link)
                    print(f" 获取不重复新链接 {len(new_token_list)}/{need_replace_count}")
                elif token_link in exist_all_url:
                    print(" 链接与现有线路重复，跳过")
            time.sleep(SLEEP_SHORT)

        if len(new_token_list) < need_replace_count:
            print(f" 仅采集到{len(new_token_list)}条有效新链接，不足{need_replace_count}条，无法完成全部替换，终止程序")
            return

        log("步骤5：替换失效链接")
        for i in range(need_replace_count):
            pos = need_replace_index[i]
            live_list[pos]["name"] = f"直播{pos + 1}"
            live_list[pos]["url"] = new_token_list[i]
            print(f" 第{pos+1}条替换为新不重复链接，名称：直播{pos+1}")

        log("步骤6：保存仓库根目录 live.txt")
        if not save_live_json(live_data):
            print(" 文件保存失败")
            return
        print(f"\n 采集完成！共替换 {need_replace_count} 条失效链接，等待工作流提交推送")

    except Exception as e:
        print(f"\n 运行异常：{str(e)}")
    finally:
        if driver:
            try:
                driver.quit()
                print("\n 浏览器已关闭")
            except Exception:
                pass

if __name__ == "__main__":
    main()
