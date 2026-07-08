import re
import os
import shutil
import platform
import time
import json
from datetime import datetime
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# ===================== 全局配置（跨仓库TV仓库配置） =====================
PROXY_URL = "http://tonkiang.us/iptvproxy.php"
CHANNEL_BASE = "http://tonkiang.us/channellist.html"
MAX_SAVE_GROUP = 3
WAIT_TIME = 80
SLEEP_LONG = 5
SLEEP_SHORT = 2
RETRY_TIMES = 2
LOOP_WAIT_INTERVAL = 3
MAX_LOOP_WAIT = 10

# 目标仓库：smxhlh/TV
TARGET_REPO_OWNER = "smxhlh"
TARGET_REPO_NAME = "TV"
TARGET_BRANCH = "master"
# 跨仓库授权token（从Actions环境变量读取）
GIT_PAT = os.getenv("REPO_PAT", "")
# 远程仓库完整地址
if GIT_PAT:
    TARGET_REMOTE_URL = f"https://{TARGET_REPO_OWNER}:{GIT_PAT}@github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}.git"
else:
    TARGET_REMOTE_URL = f"https://github.com/{TARGET_REPO_OWNER}/{TARGET_REPO_NAME}.git"

# 浏览器配置（适配GitHub Actions的Chrome）
def get_chrome_options():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.popups": 2
    }
    chrome_options.add_experimental_option("prefs", prefs)
    return chrome_options

# 路径配置：单独克隆TV仓库到临时目录，不使用脚本仓工作区
def get_workspace_paths():
    WORKSPACE = os.getenv("GITHUB_WORKSPACE", os.getcwd())
    # 临时存放TV仓库目录
    TV_REPO_DIR = os.path.join(WORKSPACE, "tv_repo_temp")
    LIVE_FILE_LOCAL = os.path.join(TV_REPO_DIR, "live.txt")
    LOG_FILE_PATH = os.path.join(WORKSPACE, "IPTV_Log.txt")
    return TV_REPO_DIR, LIVE_FILE_LOCAL, LOG_FILE_PATH

TV_REPO_DIR, LIVE_FILE_LOCAL, LOG_FILE_PATH = get_workspace_paths()

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

def write_last_update_log(content):
    try:
        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(f"【最后更新时间】：{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}\n")
            f.write(f"【更新内容】：\n{content}\n")
        print(f" 最后一次更新日志已写入：{LOG_FILE_PATH}")
        return True
    except Exception as e:
        print(f" 写入日志文件失败：{e}")
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
                print(" 文件复制后内容不一致")
                return False
    except Exception as e:
        print(f" 文件复制失败: {e}")
        return False

# ===================== Git 跨仓库操作（克隆smxhlh/TV、提交推送） =====================
def git_clone_target_repo():
    """克隆目标TV仓库到临时目录"""
    # 清理旧目录
    if os.path.exists(TV_REPO_DIR):
        shutil.rmtree(TV_REPO_DIR)
    os.makedirs(TV_REPO_DIR, exist_ok=True)
    old_cwd = os.getcwd()
    try:
        os.chdir(TV_REPO_DIR)
        print(f"开始克隆目标仓库 {TARGET_REMOTE_URL}")
        clone_res = subprocess.run(
            ["git", "clone", "-b", TARGET_BRANCH, TARGET_REMOTE_URL, "."],
            timeout=120, capture_output=True
        )
        clone_out = safe_decode(clone_res.stdout)
        clone_err = safe_decode(clone_res.stderr)
        print(f"克隆输出：{clone_out}")
        if clone_err:
            print(f"克隆错误：{clone_err}")
            return False
        return True
    finally:
        os.chdir(old_cwd)

def git_push_target_repo():
    """在TV临时仓库内提交并推送到smxhlh/TV master"""
    if not os.path.exists(LIVE_FILE_LOCAL):
        print(f" 目标文件不存在：{LIVE_FILE_LOCAL}")
        return False
    old_cwd = os.getcwd()
    os.chdir(TV_REPO_DIR)
    commit_msg = f"自动更新live.txt {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    try:
        # 配置Git提交身份
        subprocess.run(
            ["git", "config", "--global", "user.name", "GitHub Actions Bot"],
            timeout=20, capture_output=True
        )
        subprocess.run(
            ["git", "config", "--global", "user.email", "actions@github.com"],
            timeout=20, capture_output=True
        )
        # 拉取最新代码
        print("拉取TV仓库最新代码...")
        pull_res = subprocess.run(
            ["git", "pull", "--rebase", "origin", TARGET_BRANCH], timeout=60, capture_output=True
        )
        pull_out = safe_decode(pull_res.stdout)
        pull_err = safe_decode(pull_res.stderr)
        print(f"拉取结果：{pull_out}")
        if pull_err:
            print(f"拉取冲突/错误：{pull_err}")
            subprocess.run(["git", "reset", "--hard"], timeout=20, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], timeout=20, capture_output=True)
        # git status
        status_res = subprocess.run(["git", "status"], timeout=20, capture_output=True)
        print(f"TV仓库状态：{safe_decode(status_res.stdout)}")
        # 添加文件
        subprocess.run(["git", "add", "live.txt"], timeout=30, check=True, capture_output=True)
        # 提交
        commit_res = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--allow-empty"],
            timeout=30, capture_output=True
        )
        commit_out = safe_decode(commit_res.stdout)
        print(f"提交日志：{commit_out}")
        if commit_res.returncode != 0:
            print("无变更，跳过推送")
            return True
        # 推送远程
        print("推送到 smxhlh/TV master 分支")
        push_res = subprocess.run(
            ["git", "push", "origin", TARGET_BRANCH], timeout=90, check=True, capture_output=True
        )
        push_out = safe_decode(push_res.stdout)
        print(f"推送成功：{push_out}")
        return True
    except subprocess.CalledProcessError as e:
        err_out = safe_decode(e.stderr)
        print(f"Git命令失败 {' '.join(e.cmd)} 错误：{err_out}")
        return False
    except Exception as e:
        print(f"Git操作异常: {e}")
        return False
    finally:
        os.chdir(old_cwd)

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

# ===================== 文件读写 =====================
def load_live_json():
    default_data = {
        "lives": [],
        "update_seq": 0,
        "last_update": ""
    }
    # 先克隆目标仓库，再读取live.txt
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
        print(f" TV仓库内live.txt已更新，update_seq={data['update_seq']}")
        return True
    except Exception as e:
        print(f" 保存文件失败：{e}")
        return False

# ===================== 浏览器初始化 =====================
def init_browser():
    chrome_options = get_chrome_options()
    service = Service(executable_path="/usr/bin/chromedriver")
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
    update_log_content = []
    try:
        print("========== IPTV 跨仓库自动更新 smxhlh/TV ==========")
        # 1. 先克隆目标TV仓库
        log("步骤0：克隆 smxhlh/TV 仓库到临时目录")
        if not git_clone_target_repo():
            update_log_content.append("克隆目标TV仓库失败，终止运行")
            write_last_update_log("\n".join(update_log_content))
            return
        # 2. 启动浏览器
        driver = init_browser()
        print(" Chrome浏览器启动成功（无界面模式）")
        update_log_content.append("Chrome浏览器启动成功（无界面模式）")
        
        log("步骤1：读取TV仓库live.txt")
        live_data = load_live_json()
        live_list = live_data["lives"]
        print(f" 读取到 {len(live_list)} 条配置")
        update_log_content.append(f"读取到 {len(live_list)} 条配置")
        exist_all_url = {item.get("url", "") for item in live_list if item.get("url")}
        need_replace_index = []

        log("步骤2：检测原有链接可用性")
        update_log_content.append("开始检测原有链接可用性：")
        for idx, item in enumerate(live_list):
            item["name"] = f"直播{idx + 1}"
            old_url = item.get("url", "")
            if check_url_alive(driver, old_url):
                print(f" 第{idx+1}条正常，名称设为 直播{idx+1}")
                update_log_content.append(f"第{idx+1}条正常，名称：直播{idx+1}")
            else:
                print(f" 第{idx+1}条失效，待替换")
                update_log_content.append(f"第{idx+1}条失效，待替换")
                need_replace_index.append(idx)

        if not need_replace_index:
            print("\n 所有链接正常，无需替换")
            update_log_content.append("所有链接正常，无需替换")
            write_last_update_log("\n".join(update_log_content))
            return

        log("步骤3：获取新 IP/TK")
        if not safe_get(driver, PROXY_URL):
            print(" 主页面加载失败")
            update_log_content.append("主页面加载失败")
            write_last_update_log("\n".join(update_log_content))
            return
        ip_tk_list = wait_for_ip_tk(driver)
        if not ip_tk_list:
            print(" 未获取 IP/TK")
            update_log_content.append("未获取 IP/TK")
            write_last_update_log("\n".join(update_log_content))
            return
        ip_tk_list = ip_tk_list[:5]
        update_log_content.append(f"获取到 {len(ip_tk_list)} 组 IP/TK")

        log("步骤4：采集新播放链接（自动去重）")
        update_log_content.append("开始采集新播放链接：")
        for idx, (ip, tk) in enumerate(ip_tk_list, 1):
            if len(new_token_list) >= MAX_SAVE_GROUP:
                print(" 已收集足够新链接，停止采集")
                update_log_content.append("已收集足够新链接，停止采集")
                break
            channel_url = f"{CHANNEL_BASE}?ip={ip}&tk={tk}&p=4"
            if safe_get(driver, channel_url):
                token_link = wait_for_token(driver)
                if token_link and token_link not in exist_all_url and token_link not in new_token_list:
                    new_token_list.append(token_link)
                    print(f" 获取不重复新链接 {idx}")
                    update_log_content.append(f"获取不重复新链接 {idx}：{token_link}")
                elif token_link in exist_all_url:
                    print(" 链接与现有线路重复，跳过")
                    update_log_content.append(f"链接 {token_link} 与现有线路重复，跳过")
            time.sleep(SLEEP_SHORT)

        if not new_token_list:
            print(" 未采集到有效新链接，无法替换")
            update_log_content.append("未采集到有效新链接，无法替换")
            write_last_update_log("\n".join(update_log_content))
            return

        log("步骤5：替换失效链接")
        replace_num = min(len(need_replace_index), len(new_token_list))
        update_log_content.append(f"开始替换失效链接，共替换 {replace_num} 条：")
        for i in range(replace_num):
            pos = need_replace_index[i]
            live_list[pos]["name"] = f"直播{pos + 1}"
            live_list[pos]["url"] = new_token_list[i]
            print(f" 第{pos+1}条替换为新不重复链接，名称：直播{pos+1}")
            update_log_content.append(f"第{pos+1}条替换为：{new_token_list[i]}（名称：直播{pos+1}）")

        log("步骤6：保存到TV仓库live.txt")
        if not save_live_json(live_data):
            print(" live.txt保存失败")
            update_log_content.append("live.txt保存失败")
            write_last_update_log("\n".join(update_log_content))
            return
        update_log_content.append("TV仓库live.txt保存成功")

        log("步骤7：提交并推送到 smxhlh/TV master")
        git_result = git_push_target_repo()
        if git_result:
            update_log_content.append("推送至smxhlh/TV成功")
        else:
            update_log_content.append("推送至smxhlh/TV失败")

        print(f"\n 全部完成！共替换 {replace_num} 条链接")
        update_log_content.append(f"全部完成！共替换 {replace_num} 条链接")
        write_last_update_log("\n".join(update_log_content))

    except Exception as e:
        error_msg = f"运行异常：{str(e)}"
        print(f"\n {error_msg}")
        update_log_content.append(error_msg)
        write_last_update_log("\n".join(update_log_content))
    finally:
        if driver:
            try:
                driver.quit()
                print("\n 浏览器已自动关闭")
                if update_log_content:
                    update_log_content.append("浏览器已自动关闭")
            except Exception:
                pass

if __name__ == "__main__":
    main()
