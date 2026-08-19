# 批量图片等比例缩放工具 · Batch Proportional Image Resizer

一个等比例批量图片缩放器：**不裁剪、不拉伸、不填充**，只按规则把杂图归一化到固定宽度档位，方便你第二步人工裁成 16:9。

- 中文名：批量图片等比例缩放工具
- 英文名：`batch-proportional-image-resizer`

## 特性

- **按源宽分档**：`>2560 → 2560`(large)、`1920–2560 → 1920`(medium)、`1280–1920 → 1280`(small)
- **高度兜底**：算出来高度 `<720` 时，强制把高拉到 `720`、宽按比例重算（这条**优先于宽封顶**，允许宽 `>2560`）
- **不放大保护**：`w<1280 且 h>=720` 时直接保持原尺寸（发虚比凑档更糟）
- **等比、不裁、不拉伸**：使用 PIL 的 `LANCZOS` 重采样
- 支持 `jpg / png / webp / bmp / tif`
- `--sort` 按 `large / medium / small / kept` 分目录，便于按档人工裁 16:9
- `--recursive` 可递归子目录
- **跨 Pillow 版本兼容**：内置 `LANCZOS` 兼容垫片，Pillow 9/10/11/12 都能跑，无需锁定特定版本

## 安装

```bash
pip install -r requirements.txt
# 或
pip install pillow
```

> 图片缩放是硬需求，纯 Python 标准库做不了（没有 JPEG/PNG 解码器和重采样器），Pillow 是必需依赖，但版本不挑。

## 用法

```bash
python adaptive_image_resizer.py --input <图片目录> --sort
# 可选参数
#   --output <目录>     指定输出目录（默认在原目录旁生成 adaptive_output/）
#   --quality 90        输出质量（默认 90）
#   --recursive         递归处理子目录
```

`--sort` 会把结果按档位分到 `large / medium / small / kept` 四个子目录。

## 分档规则与实测示例

规则优先级：**宽度分档 → 高度兜底（可越过宽封顶）→ 不放大保护**。

| 源图 | 输出 | 落档 |
| --- | --- | --- |
| 6000×4000 | 2560×1707 | large |
| 2000×1500 | 1920×1440 | medium |
| 1500×1000 | 1280×853 | small |
| 1000×900 | 跳过（保持原尺寸） | kept |
| 1000×500 | 1440×720 | small（仅高兜底） |
| 5000×700 | 5143×720 | large（高度兜底越过宽封顶） |

以上实测图全部非 16:9、画面完整，正好对应脚本的分档逻辑。

## 说明

- 未做 EXIF 方向处理（代码内已留注释，将来加一行 `exif_transpose` 即可）。

## License

[MIT](LICENSE) © 2026 pandipper
