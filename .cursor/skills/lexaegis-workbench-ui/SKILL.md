---
name: lexaegis-workbench-ui
description: >-
  Visual and CSS rules for the LexAegis legal-privacy workbench. Use when
  changing frontend layout, typography, color, motion, or component chrome in
  frontend/src. Constrains taste-skill so landing-page defaults are not applied
  to this regulated product UI.
---

# LexAegis workbench UI

Reading this as: redesign-preserve of a regulated legal-privacy workbench for lawyers, trust-first and accessibility-first, vanilla CSS plus forest/paper tokens.

## Dials

- `DESIGN_VARIANCE=3`
- `MOTION_INTENSITY=2`
- `VISUAL_DENSITY=7`

Do not use taste-skill baseline 8 / 6 / 4.

## Tokens

Edit [frontend/src/design-tokens.css](frontend/src/design-tokens.css) first, then consume variables from [frontend/src/style.css](frontend/src/style.css). Do not add Tailwind, shadcn, Motion, or GSAP. Do not load webfonts from a CDN.

- UI stack: `--font-ui` (system sans, PingFang / YaHei)
- Display headings only: `--font-display` (system Songti / Source Han Serif SC)
- Type floor: 12 / 13 / 15 / 22 / 32. Do not ship 8-10px UI copy.
- Numbers and dates: `font-variant-numeric: tabular-nums` or `.tabular`
- Motion: `--motion` (about 180ms), `transform` / `opacity` only. Honor existing `prefers-reduced-motion`.
- Cards: background **or** divider, not both border and filled wash.

## Preserve

- Forest sidebar and paper canvas
- Four-step case flow and three-panel workspace
- Visible control names used by Playwright: `生成披露方案`, `云端摘要任务`, `生成本地摘要草稿`, `检验风险并冻结请求`, `进入工作台`, `本地生成争点候选`
- Honest capability copy: `未运行、错误和不确定均不算通过`
- `lucide-react` as the only icon family

## Do not

- Rewrite information architecture or move the sidebar to a top nav
- Add marketing motion, grain photos, broken grids, or three-equal feature-card restyles
- Use em-dash (`—`); use `-` or `无`
- Present unpublished packs, unrun attacks, or unverified isolation as available
- Claim probe-edge as legal availability
