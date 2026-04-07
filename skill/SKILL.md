---
name: pindou
description: >-
  拼豆图纸转换工具：将图片转换为拼豆（Perler/Artkal/Hama）图纸。
  支持CIEDE2000精准颜色匹配、多品牌色板切换、Floyd-Steinberg/Bayer抖动、
  多板拼接、透明背景处理、智能抠图、立体拆件，导出PNG/PDF。
  当用户提到拼豆、perler beads、豆豆图纸、像素画转拼豆、熨斗珠、
  hama beads、artkal、融合豆、拼拼豆豆、bead pattern时使用。
  即使用户只说"帮我把这张图变成拼豆"也应触发。
---

# 拼豆图纸助手

将任意图片转换为可执行的拼豆（Perler Beads）图纸，支持多品牌色板精确匹配。

## 脚本位置

所有 Python 脚本在 `~/.claude/skills/pindou/scripts/` 下：

| 脚本 | 用途 |
|------|------|
| `convert.py` | 主入口，串联完整转换流程 |
| `color_science.py` | CIEDE2000 颜色匹配引擎 |
| `dithering.py` | 抖动算法（Floyd-Steinberg / Bayer） |
| `grid_render.py` | 网格渲染 + PNG 导出 |
| `dithering.py` | 抖动算法（Floyd-Steinberg / Bayer） |
| `panel_generator.py` | 立体拆件面片生成 |

## 依赖

核心依赖（必须已安装）：
- Python 3.10+
- numpy
- Pillow (PIL)

可选依赖（按需安装）：
- `rembg`：智能抠图（首次使用需下载 ~170MB 模型）

## 第零步：判断图片类型

收到用户图片后，**先用视觉能力判断图片类型**，再决定走哪个流程：

| 图片类型 | 特征 | 走哪个流程 |
|---------|------|----------|
| **平面参考图** | 普通照片、插画、像素画、截图等 | → 标准转换流程 |
| **立体拼豆作品** | 照片中能看到拼豆颗粒、立体结构、熨烫痕迹 | → 立体拆件流程 |
| **不确定** | 无法判断 | → 问用户："这张图是要转成平面图纸，还是做立体拆件？" |

识别线索：立体拼豆作品通常有明显的颗粒质感、规整的圆形/方形排列、熨烫后的光泽、多个面片组合的立体结构。

---

## 标准转换流程

### 1. 用户提供图片和参数

从用户的自然语言中提取以下参数：

| 参数 | CLI 标志 | 默认值 | 说明 |
|------|---------|--------|------|
| 图片路径 | 第一个参数 | (必填) | PNG/JPG/BMP/WebP |
| 板子尺寸 | `--board WxH` | 58x58 | 每板的宽×高格数 |
| 多板拼接 | `--grid RxC` | 1x1 | R行×C列（上限5×5） |
| 色板 | `--palette NAME` | artkal_s | 见下方色板列表 |
| 排除颜色 | `--exclude A,B,C` | 无 | 逗号分隔的颜色编号 |
| 抖动算法 | `--dither floyd\|bayer` | none | 抖动类型 |
| 抖动强度 | `--dither-strength N` | 100 | 0-100 |
| 显示模式 | `--mode` | blocks+numbers | blocks/dots/numbers/blocks+numbers |
| 格子大小 | `--cell-size N` | 20 | 每格像素数 |
| 参考线间隔 | `--ref-lines N` | 10 | 每N格画粗线（0=关闭） |
| 色彩替换 | `--replace A:B` | 无 | 可多次使用 |
| 色调偏移 | `--tone-shift warm\|cool\|bright\|dark` | 无 | |
| 色调强度 | `--tone-strength N` | 30 | 0-100 |
| 最大颜色数 | `--max-colors N` | auto | 0=自动，6-8卡通，15-24照片 |
| 边缘阈值 | `--edge-threshold N` | 200 | 边缘检测灵敏度 |
| 去背景 | `--remove-bg` | 否 | 使用 rembg 去除背景 |
| 输出目录 | `--output-dir DIR` | 自动生成 | |

### 2. 执行转换

```bash
cd ~/.claude/skills/pindou
python3 scripts/convert.py <图片路径> [参数...]
```

脚本输出 JSON 到 stdout，包含输出文件列表和用量统计。

### 3. 呈现结果给用户

转换完成后：
1. 用 Read 工具展示生成的全局图纸 PNG（让用户直接看到效果）
2. 展示用量统计（使用了多少种颜色、每种多少颗）
3. 告知输出文件位置
4. 询问是否需要调整（换色板、开抖动、替换颜色等）

### 4. 调整（如需要）

用户可能要求：
- "换成 Hama 色板" → 重跑 `--palette hama_midi`
- "开抖动" → 重跑 `--dither floyd --dither-strength 50`
- "这个颜色太多了，我没有 H15 和 H23" → 重跑 `--exclude H15,H23`
- "导出 PDF" → 重跑加 `--pdf`

## 快捷模式

如果用户一句话给了所有参数，直接构造命令执行，不用逐个询问。

示例映射：

| 用户说 | 命令 |
|--------|------|
| "把 pikachu.png 转成拼豆图纸" | `convert.py pikachu.png` |
| "用 Hama 色板转换 photo.jpg，29x29 小板" | `convert.py photo.jpg --board 29x29 --palette hama_midi` |
| "2x3 拼接大图，开 Floyd 抖动" | `convert.py img.png --grid 2x3 --dither floyd` |
| "转换但我没有 S01 S05 S10" | `convert.py img.png --exclude S01,S05,S10` |

## 可用色板

查看所有色板：
```bash
python3 scripts/convert.py --list-palettes
```

查看某色板所有颜色：
```bash
python3 scripts/convert.py --list-colors hama_midi
```

当前内置：

| 名称 | 品牌 | 系列 | 颜色数 |
|------|------|------|--------|
| `artkal_s` | Artkal | S 系列 5mm 软豆 | 199 |
| `hama_midi` | Hama | Midi 5mm | 92 |
| `perler_standard` | Perler | Standard 5mm | 103 |

## 透明图片处理

上传带透明通道的 PNG 时：
- 透明区域自动识别为"不放豆"（空格）
- 空格在图纸中显示为浅灰色
- 用量统计中单独标注空格数量
- 空格不计入总豆数

## 多板拼接

使用 `--grid RxC` 指定拼接布局：
- 总尺寸 = 单板尺寸 × 拼接数（如 2x3 × 29x29 = 58x87）
- 输出：1 张全局总览（红色线标注板间分界）+ 每板独立图纸
- 每板图纸标注位置编号（如 "Board R1C2"）

## 立体拆件流程

当用户要求将物体/角色转换为立体拼豆作品时：

### Step 1：分析结构（你来做）
看用户提供的参考图片，分析其3D结构，输出拆件方案 JSON：

```json
{
  "name": "造型名称",
  "panels": [
    {
      "id": "body_front",
      "name": "躯干正面",
      "width": 30,
      "height": 40,
      "connects_to": ["body_left", "body_right"],
      "color_map": {
        "regions": [
          {"x": 0, "y": 0, "w": 30, "h": 20, "color_hint": "yellow"},
          {"x": 0, "y": 20, "w": 30, "h": 20, "color_hint": "white"}
        ]
      }
    }
  ],
  "assembly_order": ["body_front", "body_left", "body_back", "body_right"]
}
```

### Step 2：用户确认方案
展示拆件方案，让用户确认或调整面片数量、尺寸。

### Step 3：生成面片图纸
将确认的方案 JSON 保存为文件，执行：
```bash
python3 scripts/panel_generator.py plan.json --palette artkal_s --output-dir ./output/
```

### Step 4：展示结果
展示每个面片的图纸 PNG、卡槽位置、用量统计、组装顺序。

## 故障排除

| 问题 | 解决 |
|------|------|
| `ModuleNotFoundError: No module named 'numpy'` | `pip3 install numpy Pillow` |
| 转换很慢（>5秒） | 减小板子尺寸或检查图片是否过大 |
| 颜色匹配不准 | 色板 RGB 数据可能不精确，尝试换色板 |
| 抠图功能不可用 | 安装 rembg：`pip3 install rembg` |
