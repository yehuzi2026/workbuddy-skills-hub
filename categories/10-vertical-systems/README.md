# 🚗 垂直业务系统（车拍拍 / 物损驾驶舱） / Vertical Business Systems

> 车拍拍车辆拍卖平台运维/排障/模板修复，物损拍卖商务驾驶舱大屏与规范。

**本分类共 5 个技能。**


| 技能文件夹 | 名称 | 简介 |
| --- | --- | --- |
| `chepaipai-ops` | chepaipai-ops | 车拍拍车辆拍卖平台（武汉宏刚行科技 wuhanhonganghang.cn）的运维、后台登录验证与端到端功能/业务链路测试。当用户要登录 wuhanhonganghang.cn 管… |
| `chepaipai-ops-playbook` | chepaipai-ops-playbook | 车拍拍(wuhanhonganghang.cn)线上运维排障实战手册——沉淀自 2026-08-13 一轮实战：业务闭环写操作验证(38/38 synthetic JWT)、FTP… |
| `chepaipai-template-fix` | chepaipai-template-fix | 车拍拍(wuhanhonganghang.cn)前端 HTML in-DOM Vue 模板「自闭合 Element Plus 组件 /> 吞掉后续兄弟节点」坑的根治 skill。覆… |
| `wusun-cockpit` | wusun-cockpit | 维护与迭代 wusun-auction 项目「商务销售全局驾驶舱」大屏（ECharts 数据看板）的专用技能。当用户要求修改驾驶舱的指标口径（如把「开票/报价」改成「询价/纯销」等… |
| `驾驶舱规范` | 驾驶舱规范 | wusun-auction「商务销售全局驾驶舱」的硬性规范与契约（布局/财务闭环状态机/询价状态流/指标口径/导航注入/验证部署）。当用户修改驾驶舱、财务页、导航、询价状态，或复用… |

## 安装

将本分类下对应的技能文件夹整体复制到 WorkBuddy 用户级技能目录：

```bash
# Windows
xcopy "%USERPROFILE%\.workbuddy\skills"  # 放入对应子文件夹
# 或直接把某个技能文件夹复制到 (Windows 示例):
C:\Users\<你>\.workbuddy\skills\<技能名>
```

放入后重启 WorkBuddy 即可在对话中触发。
