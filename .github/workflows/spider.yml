const axios = require("axios");
const cheerio = require("cheerio");
const fs = require("fs");

// 模拟浏览器请求头，防止网站拦截爬虫
const headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
  "Referer": "https://guazikan.com/",
  "Origin": "https://guazikan.com"
};

// 根据截图修正后的分类配置
const categoryMap = [
  { name: "电影", type: "20", url: "https://guazikan.com/movie" },
  { name: "连续剧", type: "30", url: "https://guazikan.com/tv" },
  { name: "综艺", type: "45", url: "https://guazikan.com/variety" },
  { name: "Top250高分", type: "60", url: "https://guazikan.com/top250" },
  { name: "榜单", type: "61", url: "https://guazikan.com/top" }
];

// 请求重试封装，最多3次重试，每次间隔2秒
async function safeGet(url, opt, retry = 3) {
  try {
    return await axios.get(url, opt);
  } catch (e) {
    if (retry > 0) {
      console.log(`请求${url}失败，剩余重试次数${retry - 1}，等待2秒重试`);
      await new Promise(r => setTimeout(r, 2000));
      return safeGet(url, opt, retry - 1);
    }
    throw new Error(`多次请求失败: ${e.message}`);
  }
}

// 抓取单页影片列表
async function getPageList(targetUrl) {
  const res = await safeGet(targetUrl, { headers, timeout: 20000 });
  const $ = cheerio.load(res.data);
  const list = [];

  // 页面无影片容器直接返回空数组，不报错
  const items = $("#movie-content > div");
  if (items.length === 0) {
    console.log(`页面${targetUrl}未找到影片容器#movie-content`);
    return [];
  }

  items.each((_, el) => {
    const aTag = $(el).find("a");
    const imgTag = $(el).find("div.poster-wrap > img");
    const rawText = aTag.text().trim();
    const detailUrl = aTag.attr("href");
    let cover = imgTag.attr("src") || "";

    if (!rawText || !detailUrl) return;

    // http转https
    if (cover.startsWith("http://")) cover = "https://" + cover.slice(7);

    const split = rawText.split("\n");
    let score = "";
    let vod_name = split[0];
    if (split.length >= 2) {
      score = split[0];
      vod_name = split[1].trim();
    }

    const vod_id = detailUrl.split("/play/")[1] || "";
    list.push({
      vod_id,
      vod_name,
      vod_pic: cover,
      vod_remarks: score
    });
  });
  return list;
}

// 抓取单分类全部页面（仅第一页）
async function getCategoryAll(targetUrl) {
  try {
    return await getPageList(targetUrl);
  } catch (err) {
    console.error(`分类页面${targetUrl}抓取完全失败:`, err.message);
    return [];
  }
}

// 主入口
async function main() {
  const allCategoryData = {};
  for (const item of categoryMap) {
    console.log(`===== 开始抓取【${item.name}】${item.url} =====`);
    const data = await getCategoryAll(item.url);
    allCategoryData[item.type] = data;
    console.log(`【${item.name}】完成，共${data.length}条影片`);
  }

  // 静态源配置 type:0，移除所有动态API字段
  const tvSourceConfig = {
    "name": "瓜仔看影视",
    "type": 0,
    "headers": {
        "User-Agent": "Mozilla/5.0 (Linux; Android TV 11) TVBox/OKYS",
        "Origin": "https://guazikan.com",
        "Referer": "https://guazikan.com/",
        "sec-ch-ua": "\"Not A(Brand\";v=\"8\", \"Chromium\";v=\"132\", \"Google Chrome\";v=\"132\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Android\"",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9"
    },
    "categoryMap": categoryMap,
    "vodIdField": "vod_id",
    "vodNameField": "vod_name",
    "vodPicField": "vod_pic",
    "vodRemarkField": "vod_remarks",
    "playUrlReg": "https://.*\\.m3u8",
    "detailUrl": "/play/{id}",
    "staticList": allCategoryData
  };

  // 写入文件，即使全部为空也生成合法json，避免进程退出
  fs.writeFileSync("./source.json", JSON.stringify(tvSourceConfig, null, 2), "utf8");
  console.log("全部抓取流程结束，已生成source.json");
}

// 全局兜底捕获，就算全部抓取失败也正常退出，返回exit code 0
main()
  .then(() => process.exit(0))
  .catch(err => {
    console.error("全局致命异常：", err);
    // 异常时生成空合法配置，防止无文件
    const emptyConfig = {
      "name": "瓜仔看影视",
      "type": 0,
      "categoryMap": categoryMap,
      "staticList": {}
    };
    fs.writeFileSync("./source.json", JSON.stringify(emptyConfig, null, 2), "utf8");
    console.log("已生成空兜底配置，任务正常结束");
    process.exit(0);
  });
