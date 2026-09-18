# D 路径 DeepSeek 公开检索摘录（人工许可前）

- 检索日：2026-09-14。只摘公开页面，**不是**本账号合同原件，**不是**已实施影响评估，**不是** `reviewed`。
- 用途：给法学成员对照「服务商治理」草案。空栏不要用口述补。
- 现状：**10 案层 A 评估完成，0 案真实发送。**

## 打开的文本

| 文件 | 版本 | 链接 |
| --- | --- | --- |
| 开放平台服务协议 | 更新 2026-04-22，生效 2026-04-29 | https://cdn.deepseek.com/policies/zh-CN/deepseek-open-platform-terms-of-service.html |
| 用户协议 | 公开页（网页/App 训练条款在 4.3） | https://cdn.deepseek.com/policies/zh-CN/deepseek-terms-of-use.html |
| 隐私政策 | 更新/生效 2026-02-10 | https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html |
| API 文档（模型/端点） | 公开文档 | https://api-docs.deepseek.com/zh-cn/ |

## 字段对照（可写入草案 / 仍须人核）

| Provider 字段 | 公开检索可写 | 本账号仍须法学核 | 依据 |
| --- | --- | --- | --- |
| legal_entity | 杭州深度求索人工智能基础技术研究有限公司 | 是否即本 API 合同抬头 | 开放平台协议文首、争议管辖 9.2 |
| product / model / endpoint | DeepSeek 开放平台 Chat API；`deepseek-v4-flash`；`https://api.deepseek.com/v1/chat/completions` | Key 是否绑该官方主机，勿指百炼 | API 文档；D 路径设计 |
| role | 协议 3.5：开发者委托其处理终端用户个人信息时，对方配合。可草案填 `processor` | 本账号有无相反约定 | 开放平台协议 3.5 |
| processing_regions | 隐私政策：境内运营收集的个人信息存于中国境内 | 本账号实际部署区 | 隐私政策「存储信息的地点」 |
| training_use | **保持 `unknown`。** 开放平台协议第 4 条无训练授权。用户协议 4.3 是网页/App，关「数据用于优化体验」。二者不要混 | 本 API 账号控制台/合同是否另授权训练 | 开放平台 4.1–4.2；用户协议 4.3；隐私政策训练退出 |
| human_access | **保持 `unknown`。** 协议 7.2 可内容处置；人工是否读请求正文未写清 | 内容审核/人工访问范围 | 开放平台 7.2 |
| retention | 可草案摘：提供服务所必需期间；网络日志依法不少于六个月。口头「3 天」作废 | 本账号正文/元数据/日志分对象期限 | 隐私政策「存储信息的期限」；《网络安全法》日志举例 |
| deletion_mechanism | 可草案摘：开发者权利请求由开发者响应；配合渠道 `api-service@deepseek.com`；主体权利 `privacy@deepseek.com`，核身份后十五个工作日 | 删除是否含本次请求正文、日志例外 | 开放平台 3.5、10.2；隐私政策第九章 |
| subprocessors | **保持 `unknown`。** 政策写有合作方/实名认证机构，**无**可核名单。不要填甲公司、乙公司 | 合同转委托名单 | 隐私政策委托处理章节 |
| contract_reference | 可草案填开放平台协议 URL | 企业纸质/电子合同编号（若有） | 上表链接 |
| contract_version | 可草案填 `2026-04-29` | 本账号点击同意的是否即该版 | 开放平台协议生效日 |
| impact_assessment_reference | **空着。** 公开条款 ≠ 已实施评估。不要填 LEX-LG-AI §4 | 法学出具已实施记录后才能填 | 一对一确认 |
| valid_until | **空着。** 公开协议无本项目有效期 | 法学定截止日 | — |
| status | `draft`。工程不点「具名复核」 | `legal_reviewer` 核上列空栏后才能点 | 系统 `POST /providers/{id}/review` |

## 系统里怎么点（法学）

1. `legal_reviewer` 打开「服务商治理」，档案 `deepseek-official-api`。
2. 核对本页与控制台/合同。能改的改完「保存为草案」。
3. `training_use`、`human_access`、分包、影响评估、`valid_until` 仍未知时，**不要**点「具名复核」。点了系统会拒，或变成假许可。
4. 复核通过后仍须：运行库包发布、该案层 B、组合判断、四类 `resisted`、Compose 隔离。然后换 `approver` 批那一次请求。

**10 案层 A 评估完成，0 案真实发送。**
