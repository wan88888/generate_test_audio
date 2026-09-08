# 测试音频生成工具

用 Microsoft Edge TTS（`en-US-AriaNeural`）批量生成英文测试音频，覆盖恐怖主义相关内容、金融诈骗、正常对照，以及按时长/分段设计的时序用例。适用于语音风控、内容审核等场景的回归测试。

## 环境要求

- Python 3.10+（当前项目虚拟环境为 3.12）
- 网络（调用 Edge TTS）
- 依赖：`edge-tts`

## 快速开始

```bash
cd generate_test_audio
python3 -m venv .venv
source .venv/bin/activate
pip install edge-tts
python generate_test_audio.py
```

请使用虚拟环境中的解释器运行。系统自带的 `python3`（例如 pyenv 全局版本）若未安装 `edge-tts`，脚本会提示安装并退出。

## 输出

脚本会在项目目录下创建 `terrorism_financial_test_audio/`：

| 文件 | 说明 |
| --- | --- |
| `T01_*.mp3` ~ `T17_*.mp3` | 17 条测试音频 |
| `test_audio_manifest.csv` | 测试清单（不含本地绝对路径） |

清单列：`ID`、`Filename`、`Category`、`Expected`、`RiskWindow`。

生成的 `.mp3` 默认不纳入 Git，可按需自行备份或重新生成。清单 CSV 会随仓库保留，便于对照用例。

## 用例一览

| ID | 类别 | 期望 | 风险窗口 |
| --- | --- | --- | --- |
| T01 | 恐怖主义 | Risk | 0-60s |
| T02 | 恐怖主义（威胁） | Risk | 0-60s |
| T03 | 恐怖主义新闻讨论（易误报） | Normal | None |
| T04 | 恐怖主义历史讨论（易误报） | Normal | None |
| T05 | 金融诈骗（索要验证码） | Risk | 0-60s |
| T06 | 金融诈骗（转账/冻户） | Risk | 0-60s |
| T07 | 金融诈骗（冒充警察） | Risk | 0-60s |
| T08 | 金融诈骗（虚假投资） | Risk | 0-60s |
| T09 | 正常银行业务 | Normal | None |
| T10 | 反诈讨论（易误报） | Normal | None |
| T11 | 恐怖主义 + 金融诈骗 | Risk | 0-60s |
| T12 | 时序：风险出现在 40–60s | Risk | 40-60s |
| T13 | 时序：风险出现在 60s 之后 | Normal | >60s |
| T14 | 20s 分段：风险在 40–60s | Risk | 40-60s |
| T15 | 20s 边界：风险跨段 | Risk | 20-60s |
| T16 | 20s 分段：风险在 0–20s | Risk | 0-20s |
| T17 | 20s 分段：风险在 40–60s | Risk | 40-60s |

`Expected` 中的 `Risk` / `Normal` 是针对「前 60 秒」检测窗口的标注。T13 把风险话术放在 60 秒之后，因此在该窗口内期望为 Normal。

## 时序说明

T12–T17 依赖朗读时长。Edge TTS 的实际语速会随环境变化，脚本**不会**保证自然语速刚好落在 20s / 40s / 60s。

若需要严格卡在这些边界：

1. 生成后用播放器或 `ffprobe` 查看实际时长
2. 微调对应文案，或在脚本外插入静音后再测

## 配置

可在 `generate_test_audio.py` 顶部修改：

| 常量 | 默认值 | 含义 |
| --- | --- | --- |
| `VOICE` | `en-US-AriaNeural` | 英语女声 |
| `RATE` | `+0%` | 语速 |
| `VOLUME` | `+0%` | 音量 |
| `OUTPUT_DIR` | `terrorism_financial_test_audio/` | 输出目录 |

文案与期望标签均在 `TEST_CASES` 中维护。

## 项目结构

```
generate_test_audio.py          # 生成脚本
README.md                       # 本说明
.gitignore
terrorism_financial_test_audio/ # 运行后生成
  ├── T01_....mp3
  ├── ...
  └── test_audio_manifest.csv
```
