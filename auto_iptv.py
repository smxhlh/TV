import asyncio
import aiohttp
import re
import datetime
import requests
import eventlet
import os
import threading
from queue import Queue
from git import Repo, GitCommandError

# ===================== 配置（重要）=====================
# 当前脚本存放分支：main
SCRIPT_BRANCH = "main"
# iptv.txt 存放/读写分支：master
DATA_BRANCH = "master"
IPTV_FILENAME = "iptv.txt"
# CI环境仓库路径，github‑action工作目录
GIT_REPO_LOCAL_PATH = "./"
# =====================================================

eventlet.monkey_patch()

urls = [
    "http://1.192.12.1:9901",
    "http://1.192.248.1:9901",
    "http://1.194.52.1:10086",
    "http://1.195.111.1:11190",
    "http://1.195.130.1:9901",
    "http://1.195.131.1:9901",
    "http://1.195.62.1:9901",
    "http://1.196.192.1:9901",
    "http://1.196.252.1:9901",
    "http://1.196.55.1:9901",
    "http://1.197.153.1:9901",
    "http://1.197.203.1:9901",
    "http://1.197.249.1:9901",
    "http://1.197.250.1:9901",
    "http://1.197.251.1:9901",
    "http://1.197.82.1:9901",
    "http://1.197.83.1:9901",
    "http://1.197.84.1:9901",
    "http://1.198.30.1:9901",
    "http://1.198.67.1:9901",
    "http://1.199.234.1:9901",
    "http://1.199.235.1:9901",
    "http://115.48.62.1:9901",
    "http://115.149.139.1:10001",
    "http://115.207.18.1:9901",
    "http://115.207.211.1:9901",
    "http://115.207.24.1:9901",
    "http://115.215.143.1:9901",
    "http://115.220.17.1:9901",
    "http://115.224.206.1:9901",
    "http://115.225.233.1:9901",
    "http://115.236.171.1:9901",
    "http://115.236.83.1:1111",
    "http://115.48.160.1:9901",
    "http://115.48.161.1:9901",
    "http://115.48.22.1:9901",
    "http://115.48.60.1:9901",
    "http://115.48.62.1:9901",
    "http://115.48.63.1:9901",
    "http://115.50.120.1:9901",
    "http://115.55.132.1:9901",
    "http://115.55.59.1:9901",
    "http://115.59.9.1:9901",
    "http://182.112.188.1:9901",
    "http://182.112.28.1:9901",
    "http://182.113.201.1:9901",
    "http://182.113.206.1:9901",
    "http://182.113.6.1:9901",
    "http://182.114.185.1:9901",
    "http://182.114.212.1:9901",
    "http://182.114.214.1:9901",
    "http://182.114.215.1:9901",
    "http://182.114.48.1:9901",
    "http://182.114.49.1:9901",
    "http://182.114.50.1:9901",
    "http://182.117.83.1:9901",
    "http://182.117.136.1:9901",
    "http://182.117.90.1:9901",
    "http://182.120.229.1:9901",
    "http://182.122.122.1:9901",
    "http://182.122.73.1:10086",
    "http://182.125.172.1:9901",
    "http://182.126.114.1:9901",
    "http://182.126.115.1:9901",
    "http://182.126.119.1:9901",
    "http://182.150.25.1:9901",
    "http://182.241.192.1:9901",
    "http://182.241.193.1:9901",
    "http://182.241.194.1:9901",
    "http://182.34.67.1:9901",
    "http://182.46.196.1:9901",
    "http://183.0.186.1:8888",
    "http://183.0.186.1:9900",
    "http://183.10.180.1:9901",
    "http://183.10.181.1:9901",
    "http://183.131.246.1:9901",
    "http://183.136.148.1:9901",
    "http://183.203.147.1:9901",
    "http://183.203.151.1:9901",
    "http://183.238.113.1:8883",
    "http://183.239.226.1:9901",
    "http://183.24.48.1:9901",
    "http://183.255.41.1:9901",
    "http://183.63.15.1:9901",
    "http://183.94.146.1:2222",
]


def git_switch_data_branch(repo_path: str):
    """切换到master分支，拉取最新，用于读写iptv.txt"""
    repo = Repo(repo_path)
    # CI环境配置git用户
    repo.config_writer().set_value("user", "name", "github‑actions[bot]").release()
    repo.config_writer().set_value("user", "email", "github‑actions[bot]@users.noreply.github.com").release()
    repo.git.checkout(DATA_BRANCH)
    repo.remotes.origin.pull()
    print(f"✅已切换并拉取 {DATA_BRANCH} 分支最新代码")
    return repo


def git_commit_push(repo: Repo, file_name: str, commit_msg="auto update iptv.txt from github actions"):
    try:
        repo.index.add([file_name])
        repo.index.commit(commit_msg)
        repo.remotes.origin.push()
        print(f"✅推送成功到 {DATA_BRANCH} 分支")
    except GitCommandError as e:
        print(f"❌git操作异常 {e}")
        raise


def read_git_iptv(repo_path: str):
    file_full = os.path.join(repo_path, IPTV_FILENAME)
    old_channels = []
    if not os.path.exists(file_full):
        print(f"⚠️ {DATA_BRANCH}分支下 {IPTV_FILENAME} 不存在，无旧频道")
        return old_channels
    with open(file_full, "r", encoding="utf‑8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "#genre#" in line:
                continue
            if "," in line:
                name, url = line.split(",", 1)
                old_channels.append((name.strip(), url.strip()))
    print(f"📂读取 {DATA_BRANCH} 旧频道数量：{len(old_channels)}")
    return old_channels


async def modify_urls(url):
    modified_urls = []
    ip_start_index = url.find("//") + 2
    ip_end_index = url.find(":", ip_start_index)
    base_url = url[:ip_start_index]
    ip_address = url[ip_start_index:ip_end_index]
    port = url[ip_end_index:]
    ip_end = "/iptv/live/1000.json?key=txiptv"
    for i in range(1, 256):
        modified_ip = f"{ip_address[:‑1]}{i}"
        modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
        modified_urls.append(modified_url)
    return modified_urls


async def is_url_accessible(session, url, semaphore):
    async with semaphore:
        try:
            async with session.get(url, timeout=0.5) as response:
                if response.status == 200:
                    current_time = datetime.datetime.now().strftime("%Y‑%m‑%d %H:%M:%S")
                    print(f"{current_time} {url}")
                    return url
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    return None


async def check_urls(session, urls, semaphore):
    tasks = []
    for url in urls:
        url = url.strip()
        modified_urls = await modify_urls(url)
        for modified_url in modified_urls:
            task = asyncio.create_task(is_url_accessible(session, modified_url, semaphore))
            tasks.append(task)
    results = await asyncio.gather(*tasks)
    valid_urls = [result for result in results if result]
    return valid_urls


async def fetch_json(session, url, semaphore):
    async with semaphore:
        try:
            ip_start_index = url.find("//") + 2
            ip_dot_start = url.find(".") + 1
            ip_index_second = url.find("/", ip_dot_start)
            base_url = url[:ip_start_index]
            ip_address = url[ip_start_index:ip_index_second]
            url_x = f"{base_url}{ip_address}"
            json_url = f"{url}"
            async with session.get(json_url, timeout=0.5) as response:
                json_data = await response.json()
                results = []
                try:
                    for item in json_data['data']:
                        if isinstance(item, dict):
                            name = item.get('name')
                            urlx = item.get('url')
                            if ',' in urlx:
                                urlx = "aaaaaaaa"
                            if 'http' in urlx:
                                urld = f"{urlx}"
                            else:
                                urld = f"{url_x}{urlx}"
                            if name and urlx:
                                name = name.replace("cctv", "CCTV")
                                name = name.replace("中央", "CCTV")
                                name = name.replace("央视", "CCTV")
                                name = name.replace("高清", "")
                                name = name.replace("超高", "")
                                name = name.replace("HD", "")
                                name = name.replace("标清", "")
                                name = name.replace("频道", "")
                                name = name.replace("-", "")
                                name = name.replace(" ", "")
                                name = name.replace("PLUS", "+")
                                name = name.replace("＋", "+")
                                name = name.replace("(", "")
                                name = name.replace(")", "")
                                name = re.sub(r"CCTV(\\d+)台", r"CCTV\\1", name)
                                name = name.replace("CCTV1综合", "CCTV1")
                                name = name.replace("CCTV2财经", "CCTV2")
                                name = name.replace("CCTV3综艺", "CCTV3")
                                name = name.replace("CCTV4国际", "CCTV4")
                                name = name.replace("CCTV4中文国际", "CCTV4")
                                name = name.replace("CCTV4欧洲", "CCTV4")
                                name = name.replace("CCTV5体育", "CCTV5")
                                name = name.replace("CCTV6电影", "CCTV6")
                                name = name.replace("CCTV7军事", "CCTV7")
                                name = name.replace("CCTV7军农", "CCTV7")
                                name = name.replace("CCTV7农业", "CCTV7")
                                name = name.replace("CCTV7国防军事", "CCTV7")
                                name = name.replace("CCTV8电视剧", "CCTV8")
                                name = name.replace("CCTV9记录", "CCTV9")
                                name = name.replace("CCTV9纪录", "CCTV9")
                                name = name.replace("CCTV10科教", "CCTV10")
                                name = name.replace("CCTV11戏曲", "CCTV11")
                                name = name.replace("CCTV12社会与法", "CCTV12")
                                name = name.replace("CCTV13新闻", "CCTV13")
                                name = name.replace("CCTV新闻", "CCTV13")
                                name = name.replace("CCTV14少儿", "CCTV14")
                                name = name.replace("CCTV15音乐", "CCTV15")
                                name = name.replace("CCTV16奥林匹克", "CCTV16")
                                name = name.replace("CCTV17农业农村", "CCTV17")
                                name = name.replace("CCTV17农业", "CCTV17")
                                name = name.replace("CCTV5+体育赛视", "CCTV5+")
                                name = name.replace("CCTV5+体育赛事", "CCTV5+")
                                name = name.replace("CCTV5+体育", "CCTV5+")
                                results.append(f"{name},{urld}")
                except Exception:
                    pass
                return results
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return []


def channel_key(channel_name):
    match = re.search(r'\d+', channel_name)
    if match:
        return int(match.group())
    else:
        return float('inf')


async def main():
    # 1.切换到master分支拉取，读取iptv.txt
    repo = git_switch_data_branch(GIT_REPO_LOCAL_PATH)
    old_channel_tuple = read_git_iptv(GIT_REPO_LOCAL_PATH)
    old_raw = [f"{n},{u}" for n, u in old_channel_tuple]

    # 2.网段扫描获取新频道
    x_urls = []
    for url in urls:
        url = url.strip()
        ip_start_index = url.find("//") + 2
        ip_end_index = url.find(":", ip_start_index)
        ip_dot_start = url.find(".") + 1
        ip_dot_second = url.find(".", ip_dot_start) + 1
        ip_dot_three = url.find(".", ip_dot_second) + 1
        base_url = url[:ip_start_index]
        ip_address = url[ip_start_index:ip_dot_three]
        port = url[ip_end_index:]
        modified_ip = f"{ip_address}1"
        x_url = f"{base_url}{modified_ip}{port}"
        x_urls.append(x_url)
    unique_urls = set(x_urls)

    semaphore = asyncio.Semaphore(500)
    scan_new_channels = []
    async with aiohttp.ClientSession() as session:
        scan_valid_api = await check_urls(session, unique_urls, semaphore)
        tasks = []
        for api in scan_valid_api:
            tasks.append(asyncio.create_task(fetch_json(session, api, semaphore)))
        res = await asyncio.gather(*tasks)
        for sub in res:
            scan_new_channels.extend(sub)
    print(f"\n🔍网段扫描得到频道数量：{len(scan_new_channels)}")

    # 3.合并旧频道+扫描新频道，统一测速过滤失效
    all_to_test = old_raw + scan_new_channels
    print(f"🧪待测速总频道(旧+扫描): {len(all_to_test)}")

    eventlet.monkey_patch()
    task_queue = eventlet.Queue()
    valid_after_test = []
    error_channels = []

    def worker():
        while True:
            item = task_queue.get()
            if item is None:
                task_queue.task_done()
                break
            channel_name, channel_url = item.split(',')
            try:
                channel_url_t = channel_url.rstrip(channel_url.split('/')[-1])
                lines = requests.get(channel_url, timeout=1).text.strip().split('\n')
                ts_lists = [line.split('/')[-1] for line in lines if not line.startswith('#')]
                ts_lists_0 = ts_lists[0].rstrip(ts_lists[0].split('.ts')[-1])
                ts_url = channel_url_t + ts_lists[0]
                with eventlet.Timeout(5, False):
                    start_time = datetime.datetime.now().timestamp()
                    content = requests.get(ts_url, timeout=1).content
                    end_time = datetime.datetime.now().timestamp()
                    response_time = end_time - start_time
                if content:
                    with open(ts_lists_0, 'ab') as f:
                        f.write(content)
                    file_size = len(content)
                    download_speed = file_size / response_time / 1024
                    normalized_speed = min(max(download_speed / 1024, 0.001), 100)
                    os.remove(ts_lists_0)
                    valid_after_test.append((channel_name, channel_url, f"{normalized_speed:.3f} MB/s"))
                    progress = (len(valid_after_test)+len(error_channels)) / len(all_to_test)*100
                    now = datetime.datetime.now().strftime("%Y‑%m‑%d %H:%M:%S")
                    print(f"{now} 可用:{len(valid_after_test)} 失效:{len(error_channels)} 进度:{progress:.2f}%")
            except Exception:
                error_channels.append((channel_name, channel_url))
                progress = (len(valid_after_test)+len(error_channels)) / len(all_to_test)*100
                now = datetime.datetime.now().strftime("%Y‑%m‑%d %H:%M:%S")
                print(f"{now} 可用:{len(valid_after_test)} 失效:{len(error_channels)} 进度:{progress:.2f}%")
            task_queue.task_done()

    num_workers = 10
    for _ in range(num_workers):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
    for item in all_to_test:
        task_queue.put(item)
    task_queue.join()

    # url去重
    seen_url = set()
    final_list = []
    for name, url, speed in valid_after_test:
        if url not in seen_url:
            seen_url.add(url)
            final_list.append((name, url, speed))

    # 排序逻辑
    final_list.sort(key=lambda x: (x[0], -float(x[2].split()[0])))
    final_list.sort(key=lambda x: channel_key(x[0]))
    result_counter = 8

    # 输出写入master分支下的iptv.txt
    output_file = os.path.join(GIT_REPO_LOCAL_PATH, IPTV_FILENAME)
    with open(output_file, 'w', encoding='utf‑8') as file:
        channel_counters = {}
        file.write('央视频道,#genre#\n')
        for result in final_list:
            cn, cu, sp = result
            if 'CCTV' in cn:
                if cn in channel_counters:
                    if channel_counters[cn] >= result_counter:
                        continue
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] += 1
                else:
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] = 1

        channel_counters = {}
        file.write('卫视频道,#genre#\n')
        for result in final_list:
            cn, cu, sp = result
            if '卫视' in cn:
                if cn in channel_counters:
                    if channel_counters[cn] >= result_counter:
                        continue
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] +=1
                else:
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] =1

        channel_counters = {}
        file.write('本地频道,#genre#\n')
        for result in final_list:
            cn, cu, sp = result
            if '河南' in cn:
                if cn in channel_counters:
                    if channel_counters[cn] >= result_counter:
                        continue
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] +=1
                else:
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] =1

        channel_counters = {}
        file.write('其他频道,#genre#\n')
        for result in final_list:
            cn, cu, sp = result
            if 'CCTV' not in cn and '卫视' not in cn and '河南' not in cn:
                if cn in channel_counters:
                    if channel_counters[cn] >= result_counter:
                        continue
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] +=1
                else:
                    file.write(f"{cn},{cu}\n")
                    channel_counters[cn] =1

    print(f"\n✅处理完成，最终有效频道 {len(final_list)}")
    # 提交推送回master分支
    git_commit_push(repo, IPTV_FILENAME, commit_msg=f"auto update iptv {datetime.datetime.now()}")


if __name__ == "__main__":
    asyncio.run(main())
