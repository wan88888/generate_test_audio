# 测试音频生成工具

用 Microsoft Edge TTS 把文本转成 MP3，给语音风控、内容审核等场景做回归测试。

在网页里粘贴任意文本即可合成、试听、下载。仓库里的 17 条英文用例保存在 `presets.json`，可从页面下拉框填入后再改。

## 环境要求

- Python 3.10+（当前虚拟环境为 3.12）
- 网络（调用 Edge TTS）

```bash
cd generate_test_audio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

请使用虚拟环境中的解释器。

## 启动

```bash
source .venv/bin/activate
python -m uvicorn web_app:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000

- 把文本粘贴进输入框即可生成
- 可选：从 T01–T17 填入已有用例；页面会显示类别、期望和风险窗口
- 已改过文案再换用例时会先确认，避免误覆盖
- 合成后显示实际时长，并对照当前用例的风险窗口是否被覆盖到
- 可切换音色、语速，合成后直接试听或下载 MP3
- 文本上限 8000 字符

默认音色是 `en-US-AriaNeural`。用例文案在 `presets.json` 中维护。

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

T12–T17 依赖朗读时长。Edge TTS 的实际语速会随环境变化，**不会**保证刚好落在 20s / 40s / 60s。需要卡边界时，生成后查看实际时长，再微调文案。

## 项目结构

```
web_app.py      # 网页服务
static/         # 页面、样式、前端脚本
presets.json    # T01–T17 用例文案与标注
requirements.txt
README.md
```
