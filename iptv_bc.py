import re
import os
import shutil
import platform
import time
import random
import json
from datetime import datetime
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# ===================== 全局配置（无代理优化版） =====================
PROXY_URL = "http://tonkiang.us/iptvproxy.php"
CHANNEL_BASE = "http://tonkiang.us/channellist.html"
MAX_SAVE_GROUP = 3
WAIT_TIME = 120    # 延长页面等待至120秒，网络慢容错
SLEEP_LONG_MIN = 6
SLEEP_LONG_MAX = 12
SLEEP_SHORT_MIN = 2
SLEEP_SHORT_MAX = 5
RETRY_TIMES = 3    # 增加重试次数
LOOP_WAIT_INTERVAL = 3
MAX_LOOP_WAIT = 10
# 随机UA池，规避固定UA被封禁
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0 Safari/537.36"
]

# 路径配置（GitHub Actions）
def get_workspace_paths():
    WORKSPACE = os.getenv("GITHUB_WORKSPACE", os.getcwd())
    LIVE_FILE_LOCAL = os.path.join(WORKSPACE, "live.txt")
    GIT_REPO_DIR = WORKSPACE
    GIT_TARGET_FILE = LIVE_FILE_LOCAL
    LOG_FILE_PATH = os.path.join(WORKSPACE, "IPTV_Log.txt")
    return LIVE_FILE_LOCAL, GIT_REPO_DIR, GIT_TARGET_FILE, LOG_FILE_PATH

LIVE_FILE_LOCAL, GIT_REPO_DIR, GIT_TARGET_FILE, LOG_FILE_PATH = get_workspace_paths()

# 失效关键字，区分【拦截关键字】和普通失效关键字
BLOCK_KEYWORDS = {"这是一个境外网页", "当前无法访问"}
INVALID_KEYWORDS = {
    "已经失效", "重新订阅", "欢迎来到", "提供订阅",
    "tonkiang.us", "系统内部异常", "end1"
}
ALL_INVALID = BLOCK_KEYWORDS.union(INVALID_KEYWORDS)

# ===================== 工具函数 =====================
def log(step_desc):
    print(f"\n【{step_desc}】")
    print("-" * 60)

def random_sleep(min_t, max_t):
    t = random.uniform(min_t, max_t)
    time.sleep(t)
    return round(t, 2)

def write_last_update_log(content):
    try:
        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(f"【最后更新时间】：{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}\n")
            f.write(f"【更新内容】：\n{content}\n")
        print(f" 日志写入完成：{LOG_FILE_PATH}")
        return True
    except Exception as e:
        print(f" 日志写入失败：{e}")
        return False

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

def force_copy_file(src, dst):
    try:
        with open(src, "rb") as f_src:
            content = f_src.read()
        with open(dst, "wb") as f_dst:
            f_dst.write(content)
        with open(src, "rb") as f1, open(dst, "rb") as f2:
            if f1.read() == f2.read():
                return True
            else:
                print(" 文件复制内容不一致")
                return False
    except Exception as e:
        print(f" 文件复制失败: {e}")
        return False

# ===================== Git 推送 =====================
def git_push_file():
    if not os.path.exists(LIVE_FILE_LOCAL):
        print(f" 源文件不存在：{LIVE_FILE_LOCAL}")
        return False

    old_cwd = os.getcwd()
    os.chdir(GIT_REPO_DIR)
    commit_msg = f"自动更新 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    try:
        subprocess.run(["git", "config", "--global", "user.name", "GitHub Actions Bot"], timeout=20, capture_output=True)
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], timeout=20, capture_output=True)

        print(" 拉取远程代码...")
        pull_res = subprocess.run(["git", "pull", "--rebase"], timeout=60, capture_output=True)
        pull_out = safe_decode(pull_res.stdout)
        pull_err = safe_decode(pull_res.stderr)
        print(f" 拉取输出：{pull_out}")
        if pull_err:
            print(f" 拉取警告：{pull_err}")
            subprocess.run(["git", "reset", "--hard"], timeout=20, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], timeout=20, capture_output=True)

        subprocess.run(["git", "add", "."], timeout=30, capture_output=True)
        commit_res = subprocess.run(["git", "commit", "-m", commit_msg, "--allow-empty"], timeout=30, capture_output=True)
        if commit_res.returncode != 0:
            print(" 无变更，跳过推送")
            return True

        subprocess.run(["git", "push", "origin", "main"], timeout=60, check=True, capture_output=True)
        print(" Git推送完成")
        return True
    except Exception as e:
        print(f"Git操作异常：{e}")
        return False
    finally:
        os.chdir(old_cwd)

# ===================== 链接检测（区分拦截/失效） =====================
def check_url_alive(driver, url):
    if not url or not url.startswith(("http://", "https://")):
        print(" 无效链接，判定失效")
        return False, False
    try:
        if not safe_get(driver, url):
            print(" 页面加载超时，失效")
            return False, False
        page_text = driver.find_element("tag name", "body").text.strip()
        if len(page_text) < 5:
            print(" 页面空白，失效")
            return False, False

        # 判断是否被网络拦截
        hit_block = any(k in page_text for k in BLOCK_KEYWORDS)
        if hit_block:
            print(" 命中境外拦截提示，访问被阻断")
            return False, True

        hit_invalid = any(k in page_text for k in INVALID_KEYWORDS)
        if hit_invalid:
            print(" 命中失效关键词，链接作废")
            return False, False
    except Exception as e:
        print(f"检测异常：{str(e)[:40]}")
        return False, False
    return True, False

# ===================== 文件读写 =====================
def load_live_json():
    default_data = {"lives": [], "update_seq": 0, "last_update": ""}
    if not os.path.exists(LIVE_FILE_LOCAL):
        save_live_json(default_data)
        return default_data
    try:
        with open(LIVE_FILE_LOCAL, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("update_seq", 0)
        data.setdefault("last_update", "")
        data.setdefault("lives", [])
        return data
    except Exception:
        return default_data

def save_live_json(data):
    data["update_seq"] += 1
    data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        with open(LIVE_FILE_LOCAL, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return os.path.getsize(LIVE_FILE_LOCAL) > 0
    except Exception as e:
        print(f"保存失败：{e}")
        return False

# ===================== 浏览器初始化（强伪装无代理版） =====================
def init_browser():
    chrome_options = Options()
    # 无头模式
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--incognito")
    # 随机UA
    chrome_options.add_argument(f"user-agent={random.choice(UA_LIST)}")
    # 指纹伪装核心参数
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-webrtc")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    # 屏蔽弹窗、通知、自动下载
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2,
        "profile.default_content_setting_values.automatic_downloads": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    # 清除webdriver标记
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        delete navigator.webdriver;
        window.chrome = { runtime: {} };
        """
    })
    # 关闭导航检测
    driver.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": random.choice(UA_LIST)})
    driver.set_page_load_timeout(WAIT_TIME)
    driver.set_script_timeout(WAIT_TIME)
    driver.implicitly_wait(WAIT_TIME)
    return driver

def safe_get(driver, url):
    for i in range(RETRY_TIMES + 1):
        try:
            driver.get(url)
            return True
        except (TimeoutException, WebDriverException):
            t = random_sleep(SLEEP_LONG_MIN, SLEEP_LONG_MAX)
            print(f"加载失败，第{i+1}次重试，休眠{t}s")
    return False

def wait_for_ip_tk(driver):
    loop_count = 0
    while loop_count < MAX_LOOP_WAIT:
        html = driver.page_source
        pattern = re.compile(r"ip=([\d\.]+)\s*&(?:amp;)?tk=([a-zA-Z0-9]+)")
        matches = pattern.findall(html)
        if matches:
            return list(dict.fromkeys(matches))
        loop_count += 1
        random_sleep(LOOP_WAIT_INTERVAL, LOOP_WAIT_INTERVAL + 2)
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
        random_sleep(LOOP_WAIT_INTERVAL, LOOP_WAIT_INTERVAL + 2)
    return None

# ===================== 主程序（拦截不终止，容错增强） =====================
def main():
    driver = None
    new_token_list = []
    update_log_content = []
    task_success = True
    try:
        print("========== IPTV自动更新（无代理强伪装版） ==========")
        driver = init_browser()
        print(" Chromium浏览器启动成功")
        update_log_content.append("Chromium浏览器启动成功")

        log("步骤1：读取本地live.txt")
        live_data = load_live_json()
        live_list = live_data["lives"]
        exist_all_url = {item.get("url", "") for item in live_list if item.get("url")}
        print(f"读取现有 {len(live_list)} 条直播线路")
        update_log_content.append(f"读取现有 {len(live_list)} 条直播线路")

        need_replace_index = []
        log("步骤2：检测原有线路存活")
        for idx, item in enumerate(live_list):
            item["name"] = f"直播{idx + 1}"
            ok, is_block = check_url_alive(driver, item.get("url", ""))
            if ok:
                update_log_content.append(f"第{idx+1}条线路正常")
            else:
                need_replace_index.append(idx)
                update_log_content.append(f"第{idx+1}条失效，待替换")

        if not need_replace_index:
            print(" 所有线路正常，无需更新")
            update_log_content.append("所有线路正常，无需更新")
            save_live_json(live_data)
            git_push_file()
            write_last_update_log("\n".join(update_log_content))
            return

        log("步骤3：访问采集主页获取IP/TK")
        main_page_ok = safe_get(driver, PROXY_URL)
        if not main_page_ok:
            print(" 采集主页访问超时/拦截，无法获取新源，保留原有线路直接提交")
            update_log_content.append("采集主页被网络拦截，无法获取新链接，保留现有线路")
            save_live_json(live_data)
            git_push_file()
            write_last_update_log("\n".join(update_log_content))
            return

        ip_tk_list = wait_for_ip_tk(driver)
        if not ip_tk_list:
            print(" 页面未解析到IP/TK，无新链接，保留原有线路")
            update_log_content.append("未解析到IP/TK，无新链接，保留原有线路")
            save_live_json(live_data)
            git_push_file()
            write_last_update_log("\n".join(update_log_content))
            return
        ip_tk_list = ip_tk_list[:5]
        update_log_content.append(f"获取 {len(ip_tk_list)} 组IP/TK，开始逐个采集")

        log("步骤4：循环采集新播放链接（拦截则跳过当前组）")
        for idx, (ip, tk) in enumerate(ip_tk_list, 1):
            if len(new_token_list) >= MAX_SAVE_GROUP:
                update_log_content.append("已收集足够新链接，停止采集")
                break
            channel_url = f"{CHANNEL_BASE}?ip={ip}&tk={tk}&p=4"
            page_ok = safe_get(driver, channel_url)
            if not page_ok:
                update_log_content.append(f"第{idx}组IP/TK页面拦截/超时，跳过")
                random_sleep(SLEEP_SHORT_MIN, SLEEP_SHORT_MAX)
                continue
            token_link = wait_for_token(driver)
            if token_link and token_link not in exist_all_url and token_link not in new_token_list:
                new_token_list.append(token_link)
                update_log_content.append(f"成功获取新链接{idx}：{token_link}")
            elif token_link in exist_all_url:
                update_log_content.append(f"链接{token_link}已存在，跳过")
            random_sleep(SLEEP_SHORT_MIN, SLEEP_SHORT_MAX)

        log("步骤5：替换失效线路（有新链接才替换）")
        if new_token_list:
            replace_num = min(len(need_replace_index), len(new_token_list))
            update_log_content.append(f"共替换 {replace_num} 条失效线路")
            for i in range(replace_num):
                pos = need_replace_index[i]
                live_list[pos]["url"] = new_token_list[i]
                live_list[pos]["name"] = f"直播{pos + 1}"
                update_log_content.append(f"第{pos+1}条替换为新链接")
        else:
            update_log_content.append("本次未采集到可用新链接，保留原有失效线路")

        # 保存文件并推送
        save_live_json(live_data)
        git_res = git_push_file()
        update_log_content.append(f"Git推送结果：{'成功' if git_res else '失败'}")

    except Exception as e:
        task_success = False
        err_msg = f"全局异常：{str(e)}"
        print(err_msg)
        update_log_content.append(err_msg)
        # 异常兜底：依然保存现有数据并推送，防止仓库清空
        try:
            save_live_json(live_data)
            git_push_file()
            update_log_content.append("异常兜底：已保存原始线路并推送仓库")
        except:
            pass
    finally:
        if driver:
            try:
                driver.quit()
                update_log_content.append("浏览器正常关闭")
            except:
                pass
        write_last_update_log("\n".join(update_log_content))
        # 不主动抛出异常，避免 exit code=1 阻断流程
        if not task_success:
            print("本次采集存在异常，但已完成兜底保存与推送")

if __name__ == "__main__":
    main()
