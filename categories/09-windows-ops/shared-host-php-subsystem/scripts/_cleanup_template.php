<?php
/**
 * 临时清理脚本模板（shared-host-php-subsystem skill）
 *
 * 用途：子系统开发/验证时产生的演示数据、临时表数据软删。
 * 用法：
 *   1) 把本文件放到 deploy_src/<子系统>/api/ 下，命名为 _cleanup_xxx.php
 *   2) FTP 上传（manifest 远程路径含 wwwroot/ 前缀）
 *   3) 浏览器/curl 访问该 php 执行清理
 *   4) 用 ftplib(encoding='latin-1') 删线 + curl 验 404 + 删本地与部署清单
 *
 * 关键纪律（见 skill references/pitfalls.md P7）：
 *   - 业务删除一律软删 is_deleted=1，不物理删
 *   - DB 入口用本子系统独立连接函数（如 hg_insu_pdo()），不复用主站
 *   - 跑完必须删脚本，绝不留公网可访问的清理端点
 */

require_once __DIR__ . '/_db.php';          // 提供 hg_insu_pdo() 等连接函数

$pdo = hg_insu_pdo();

// ===== 按需修改这一段 =====
$table = 'hg_insu_quote';                   // 要清理的表
$ids   = [10, 11];                          // 要软删的主键 id 列表
// ===========================

if (!is_array($ids) || count($ids) === 0) {
    echo json_encode(['code' => 400, 'msg' => '未配置 ids']);
    exit;
}
$safeIds = array_map('intval', $ids);
$sql = "UPDATE `{$table}` SET is_deleted = 1 WHERE id IN (" . implode(',', $safeIds) . ")";
$st = $pdo->prepare($sql);
$st->execute();
echo json_encode([
    'code'    => 0,
    'table'   => $table,
    'deleted' => $st->rowCount(),
], JSON_UNESCAPED_UNICODE);
