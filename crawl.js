const axios = require("axios");
const cheerio = require("cheerio");
const fs = require("fs");

// 模拟浏览器请求头，防止网站拦截爬虫
const headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
  "Referer": "https://guazikan.com/",
  "Origin": "https://guazikan.com"
};

// ====== 根据截图修正后的分类配置 ======
const categoryMap = [
  { name: "电影", type: "20", url: "https://guazikan.com/movie" },
  { name: "连续剧", type: "30", url: "https://guazikan.com/tv" },
  { name: "综艺", type: "45", url: "https://guazikan.com/variety" },
  { name: "Top250高分", type: "60", url: "https://guazikan.com/top250" },
  { name: "榜单", type: "61", url: "https://guazikan.com/top" }
];

// 通用抓取单分类页面函数
async function getCategoryList(targetUrl) {
  const res = await axios.get(targetUrl, { headers, timeout: 15000 });
  const $ = cheerio.load(res.data);
  const list = [];

  $("#movie-content > div").each((_, el) => {
    const aTag = $(el).find("a");
    const imgTag = $(el).find("div.poster-wrap > img");
    const rawText = aTag.text().trim();
    const detailUrl = aTag.attr("href");
    let cover = imgTag.attr("src") || "";

    // 过滤无效数据
    if (!rawText || !detailUrl) return;

    // http图片自动转https，避免TV加载失败
    if (cover.startsWith("http://")) cover = "https://" + cover.slice(7);

    // 拆分评分、片名
    const split = rawText.split("\n");
    let score = "";
    let vod_name = split[0];
    if (split.length >= 2) {
      score = split[0];
      vod_name = split[1].trim();
    }

    // 提取唯一影片ID
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

// 主函数：遍历所有分类抓取
async function main() {
  const allCategoryData = {};
  for (const item of categoryMap) {
    console.log(`正在抓取【${item.name}】地址：${item.url}`);
    try {
      const data = await getCategoryList(item.url);
      allCategoryData[item.type] = data;
      console.log(`【${item.name}】抓取成功，共${data.length}部影片`);
    } catch (err)
      console.error(`【${item.name}】抓取失败：`, err.message);
      allCategoryData[item.type] = [];
    }
  }

  // 生成TV标准配置文件（完全匹配OK影视格式）
  const tvSourceConfig = {
    "name": "瓜仔看影视",
    "type": 1,
    "api": "https://guazikan.com",
    "backupApi": "https://guazikan.com",
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
    "searchUrl": "/pro/vod?pg={page}&wd={kw}",
    "categoryUrl": "/pro/vod?pg={page}&type={type}",
    "detailUrl": "/play?id={id}",
    "pageParam": "pg",
    "categoryMap": categoryMap,
    "vodIdField": "vod_id",
    "vodNameField": "vod_name",
    "vodPicField": "vod_pic",
    "vodRemarkField": "vod_remarks",
    "playUrlReg": "https://.*\\.m3u8",
    "staticList": allCategoryData
  };

  // 写入仓库根目录source.json，格式化换行方便查看
  fs.writeFileSync("./source.json", JSON.stringify(tvSourceConfig, null, 2), "utf8");
  console.log("全部分类抓取完成，已自动更新仓库内source.json");
}

main().catch(err => {
  console.error("全局抓取失败：", err);
  process.exit(1);
});
