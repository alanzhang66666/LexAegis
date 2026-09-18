# LexAegis · 案隐盾

本地优先的法律披露工作台：边侧整理原文与身份映射，律师批准完整请求后由独立网关调云，结果回边侧校核。版本 **V1.0**（`1.0.0`）。正式外发失败关闭。非正式发行。

## 怎么跑

`python -m pip install -e ".[test]"` → `cd frontend && pnpm install --frozen-lockfile && pnpm build` → `lexaegis start`。工作台 **http://127.0.0.1:8765**（不要用 `localhost`）。演示只接受内置合成材料。口令看终端。

## 技术栈

Python 3.12+ / FastAPI / SQLAlchemy；前端 React + Vite（`frontend/`）；隔离用 Compose。密钥只进网关。

## 目录与约定

根目录中文文件只做跳转。东西放哪：

| 找什么 | 去哪 |
| --- | --- |
| 规格 / 怎么跑 | `docs/PROJECT_MAP.md`；三角：ARCHITECTURE + VALIDATION + PROVENANCE |
| 法学现行 5 读、法计交接空表 | `docs/legal/README.md` |
| 法源表、标注 xlsx/docx | `legal/sources/`、`legal/templates/` |
| 代码 / 测试 / 包 | `lexaegis/`、`tests/`、`packs/`（无一 published） |
| 运行库、真案、交付包 | `.data/`（不入库）。交付包：`.data/outbound_packets/` |

改 `frontend/src` 先读 `.cursor/skills/lexaegis-workbench-ui`。仓库包 `2.0.0-draft.3`，`dispatch_allowed=false`。

## 当前状态（2026-09-14）

**10 案层 A 评估完成，0 案真实发送。** D 路径走一遍 = evaluate，不是 HTTP 发送。LA-001 须「本次可用」签署 + 十门全过才可谈一次发送；其余九案层 B 关闭。分词 ≠ 匿名。Compose 五项探测 ≠ 本请求隔离收据，native 不能自证隔离。

不要：发明合同/审批人；把口述当服务商 `reviewed`；发布仓库 pack；削弱 `validate_formal_gate` / `authorize_dispatch`；另编第二套门禁编号（执法只走 `outbound_gate` G 表）；把 409 当产品 bug；把工程攻击当法学 `resisted`；写「10 案已通过」或「外发已开通」。

## 下一步

补齐十门真收据后，才能对 **一次** 哈希绑定的 D 发送谈批准。一案成功不扩到十案。
