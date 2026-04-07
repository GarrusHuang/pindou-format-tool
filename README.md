# Pindou Format Tool

将图片转换为拼豆（Perler / Artkal / Hama）图纸的 Claude Code Skill。

![效果示例](https://img.shields.io/badge/colors-CIEDE2000-blue) ![Python](https://img.shields.io/badge/Python-3.10+-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

## 功能

- **图片→拼豆图纸**：上传任意图片，自动转换为可执行的拼豆图纸
- **CIEDE2000 精准颜色匹配**：基于人眼感知的色差算法，匹配最接近的豆子颜色
- **梯度对齐网格**：网格线自动 snap 到颜色边界，轮廓天然平滑
- **K-means 多数决取色**：每格用 K-means(K=2) 取主色，抗锯齿像素自动丢弃
- **颜色量化**：将图片简化为少数几种干净的色板颜色，符合拼豆实际用色逻辑
- **重排轮廓算法**：异色边界自动生成平滑轮廓，同色区域保留原始特征线条
- **多品牌色板**：Artkal S 系列（199色）、Hama Midi（92色）、Perler Standard（103色）
- **智能抠图**：rembg 自动去除背景
- **多板拼接**：支持 N×M 板拼接，自动标注分界线
- **Floyd-Steinberg / Bayer 抖动**：可选的色彩过渡增强
- **立体拆件**：Claude 视觉分析 3D 结构，自动生成面片图纸 + 卡槽设计
- **中文支持**：图纸标题和面片名称支持中文渲染

## 安装

### 作为 Claude Code Skill 使用

将 `skill/` 目录复制到 `~/.claude/skills/pindou/`：

```bash
cp -r skill/ ~/.claude/skills/pindou/
```

然后在 Claude Code 中直接说"帮我把这张图转成拼豆图纸"即可触发。

### 独立使用

```bash
# 核心依赖（必须）
pip install numpy Pillow

# 可选依赖
pip install rembg          # 智能抠图
pip install colour-science # 交叉验证（开发用）
```

## 快速开始

```bash
cd skill/

# 基础转换
python3 scripts/convert.py photo.png

# 指定板子和色板
python3 scripts/convert.py photo.png --board 29x29 --palette hama_midi

# 去背景 + 限制颜色数
python3 scripts/convert.py cartoon.png --remove-bg --max-colors 8

# 多板拼接
python3 scripts/convert.py large.png --grid 2x3 --board 29x29

# 查看可用色板
python3 scripts/convert.py --list-palettes

# 查看色板所有颜色
python3 scripts/convert.py --list-colors hama_midi
```

## 输出示例

每次转换输出：
- `*_global.png` — 带颜色编号的网格图纸（打印用）
- `*_dots.png` — 圆点模式预览（模拟真实拼豆效果）
- `pattern.json` — 完整的网格数据（可用于二次编辑）

输出 JSON 到 stdout，包含用量统计：

```json
{
  "output_dir": "pindou_output_photo",
  "files": ["photo_global.png", "photo_dots.png"],
  "statistics": {
    "total_cells": 3364,
    "filled_cells": 871,
    "empty_cells": 2493,
    "colors_used": 6,
    "breakdown": [
      {"code": "H18", "name": "Black", "count": 352},
      {"code": "H64", "name": "Pearl", "count": 247}
    ]
  }
}
```

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--board WxH` | 58x58 | 板子尺寸（格数） |
| `--grid RxC` | 1x1 | 多板拼接布局 |
| `--palette NAME` | artkal_s | 色板名称 |
| `--max-colors N` | auto | 最大颜色数（0=自动） |
| `--remove-bg` | 否 | 使用 rembg 去除背景 |
| `--exclude A,B,C` | 无 | 排除指定颜色编号 |
| `--dither floyd\|bayer` | none | 抖动算法 |
| `--dither-strength N` | 100 | 抖动强度 0-100 |
| `--mode` | blocks+numbers | 显示模式 |
| `--cell-size N` | 20 | 每格像素数 |
| `--ref-lines N` | 10 | 参考线间隔 |
| `--edge-threshold N` | 200 | 边缘检测灵敏度 |

## 算法原理

### Pipeline

```
原图 → 抠图(rembg) → 颜色量化(Sobel边缘+PIL中值切割+CIEDE2000匹配)
→ 梯度对齐网格(网格线snap到颜色边界) → K-means(K=2)多数决取色
→ 色板匹配(CIEDE2000) → 重排轮廓(reflow) → 输出PNG
```

### 关键技术

**CIEDE2000 颜色匹配**：在 CIELAB 色彩空间中计算色差，比 RGB 欧氏距离更符合人眼感知。纯 numpy 实现，通过 Sharma(2005) 参考值验证。

**梯度对齐网格**（借鉴 [perfectPixel](https://github.com/theamusing/perfectPixel)）：网格线不是均匀分割，而是微调到最近的颜色梯度峰值。让网格切割恰好落在颜色边界上，轮廓天然平滑。

**K-means(K=2) 多数决取色**：每个网格单元内用 K-means 分成 2 类，取多数色。抗锯齿的模糊像素被当成少数类自动丢弃，产出干净的色块。

**重排轮廓（Reflow）**：移除量化产生的粗糙轮廓黑格，保留原图特征黑格（眼睛、胡须等），在色块边界重新生成平滑的 1 格宽轮廓线。

## 项目结构

```
skill/
├── SKILL.md                    # Claude Code Skill 配置
├── scripts/
│   ├── convert.py              # 主转换 pipeline
│   ├── color_science.py        # CIEDE2000 颜色引擎
│   ├── dithering.py            # 抖动算法
│   ├── grid_render.py          # 网格渲染 + PNG 导出
│   └── panel_generator.py      # 立体拆件
├── data/palettes/
│   ├── artkal_s.json           # Artkal S 系列 (199 色)
│   ├── hama_midi.json          # Hama Midi (92 色)
│   └── perler_standard.json    # Perler Standard (103 色)
└── assets/fonts/
    └── NotoSansSC-Regular.ttf  # 中文字体
docs/                           # PRD 文档（不纳入版本控制）
```

## 色板数据来源

色板 RGB 数据来自 [maxcleme/beadcolors](https://github.com/maxcleme/beadcolors)（CC0 协议）。

## License

MIT
