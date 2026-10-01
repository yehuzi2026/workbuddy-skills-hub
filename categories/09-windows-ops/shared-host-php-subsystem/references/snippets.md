# 可复用代码片段（复制即用）

## A. 前端统一 API 封装（app.js 顶部）

```js
const API = '/insurance/api/index_router.php';
function api(action, params = {}) {
  const fd = new URLSearchParams();
  fd.append('action', action);
  const t = localStorage.getItem('insu_token') || localStorage.getItem('token') || '';
  if (t) fd.append('token', t);
  for (const k in params) if (params[k] !== undefined && params[k] !== null) fd.append(k, params[k]);
  return fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: fd })
    .then(r => r.json());
}
// 图片上传：FileReader 转 base64 → JSON（绕开 WAF multipart 剥离，见 P1）
function apiUpload(vehicleId, imageType, files) {
  const images = [];
  const readers = Array.from(files).map(f => new Promise(res => {
    const r = new FileReader();
    r.onload = () => res({ name: f.name, ext: f.name.split('.').pop(), data: (r.result.split(',')[1]) });
    r.readAsDataURL(f);
  }));
  return Promise.all(readers).then(ims => api('image_upload', {
    vehicle_id: vehicleId, image_type: imageType,
    images: JSON.stringify(ims)
  }));
}
```

## B. 临时清理脚本模板（跑完即删，见 P7）

```php
<?php
// _cleanup_xxx.php —— 临时用，FTP 上传 → 跑 → FTP latin-1 删 → curl 404 验证
require_once __DIR__ . '/_db.php';
$pdo = hg_insu_pdo();
$ids = [10, 11]; // 要清理的演示数据 id
$st = $pdo->prepare('UPDATE hg_insu_quote SET is_deleted = 1 WHERE id IN (' . implode(',', array_map('intval', $ids)) . ')');
$st->execute();
echo json_encode(['code' => 0, 'deleted' => $st->rowCount()]);
```

## C. FTP 部署 manifest 示例（远程路径含 wwwroot/ 前缀，见 P3）

```
# deploy_xxx.txt —— 每行：本地相对路径<空格>远程路径
insurance/admin/app.js        wwwroot/insurance/admin/app.js
insurance/admin/dashboard.php wwwroot/insurance/admin/dashboard.php
insurance/api/quote.php       wwwroot/insurance/api/quote.php
```

运行：`FTP_PASS='口令' python scripts/ftp_put_robust.py deploy_xxx.txt`

## D. 幂等建表 + 种子（sql/init.sql）

```sql
CREATE TABLE IF NOT EXISTS hg_insu_user (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  real_name VARCHAR(50),
  password VARCHAR(64),
  role ENUM('super_admin','admin') DEFAULT 'admin',
  is_deleted TINYINT DEFAULT 0,
  created_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始账号（幂等）
INSERT IGNORE INTO hg_insu_user (username, real_name, password, role)
VALUES ('admin', '超级管理员', MD5('admin123'), 'super_admin'),
       ('pricer1', '报价员-甲', MD5('admin123'), 'admin');
```

## E. PDF 生成（lib/insu_pdf.php）

```php
require_once __DIR__ . '/lib/insu_pdf.php';
$r = insu_generate_quote_pdf($vehicle, $quotes, $deciderName, 'final');
// 返回 ['code'=>0, 'pdf_url'=>'/insurance/storage/pdfs/xxx.pdf', ...]
```

## F. 部署后校验（curl 带浏览器 UA，见 P3/P4）

```bash
curl -s -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
  "http://域名/insurance/admin/app.js" | grep -c "新版本关键标识"
# 期望输出 1
```
