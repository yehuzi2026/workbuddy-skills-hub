// fetch_stats.js — 在公众号后台「首页」( /cgi-bin/home ) 的浏览器控制台执行
// 提取账号关键指标，返回 JSON 供 analyze_stats.py 使用。
//
// 用法（browser-act 场景）：
//   1) 先 navigate 到 https://mp.weixin.qq.com/cgi-bin/home
//   2) eval 本文件内容
//   3) 取 result.homeStats
//
// 注意：必须在首页才能取到「总用户数」等卡片；userAnalysis 接口常返回 HTML 而非 JSON，故以 DOM 提取为准。

function homeStats() {
  var txt = document.body.innerText || '';
  function pick(label) {
    var i = txt.indexOf(label);
    if (i < 0) return null;
    var tail = txt.substring(i + label.length, i + label.length + 40);
    var m = tail.match(/([\d][\d,]*)/);
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
  }
  return {
    total_user: pick('总用户数'),
    yesterday_read: pick('昨日阅读'),
    yesterday_share: pick('昨日分享'),
    yesterday_new_follow: pick('昨日新增关注'),
    original_count: pick('原创内容'),
    need_realname: txt.indexOf('尚未进行实名验证') >= 0,
    scrapedFrom: location.href.indexOf('/cgi-bin/home') >= 0 ? 'home' : 'other_page'
  };
}

var result = { homeStats: homeStats() };
result;
