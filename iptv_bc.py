import re
import os
import time
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# ===================== 全局配置（CI云端适配） =====================
PROXY_URL = "http://tonkiang.us/iptvproxy.php"
CHANNEL_BASE = "http://tonkiang.us/channellist.html"
MAX_SAVE_GROUP = 3
WAIT_TIME = 80
SLEEP_LONG = 5
SLEEP_SHORT = 2
RETRY_TIMES = 2
LOOP_WAIT_INTERVAL = 3
MAX_LOOP_WAIT = 10

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

# ===================== 浏览器初始化（修复缩进+读取CI驱动环境变量） =====================
def init_browser():
    chrome_options = Options()
    # CI标准无头模式
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    # 读取CI传入的chromedriver路径，修复else缩进问题
    driver_path = os.getenv("CHROME_DRIVER_PATH")
    if driver_path and os.path.exists(driver_path):
        service = Service(executable_path=driver_path)
    else:
        service = Service()

    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    driver.set_page_load_timeout(WAIT_TIME)
    driver.set_script_timeout(WAIT_TIME)
    driver.implicitly_wait(WAIT_TIME)
    return driver

def safe_get(driver, url):
    for _ in range(RETRY_TIMES + 1):
        try:
            driver.get(url)
            return True
        except (TimeoutException, WebDriverException):
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

# 页面正则提取函数
def wait_for_ip_tk(driver):
    loop_count = 0
    while loop_count < MAX_LOOP_WAIT:
        html = driver.page_source
        pattern = re.compile(r"ip=([\d\.]+)\s*&(?:amp;)?tk=([a-zA-Z0-9]+)")
        matches = pattern.findall(html)
        if matches:
            return list(dict.fromkeys(matches))
        loop_count += 1
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
        print("========== CI云端IPTV采集脚本 ==========")
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
