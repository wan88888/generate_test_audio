# 测试音频生成工具

用 Microsoft Edge TTS 把文本转成 MP3，给语音风控、内容审核等场景做回归测试。

在网页里粘贴任意文本即可合成、试听、下载。仓库里的用例保存在 `presets.json`，可从页面下拉框填入后再改。

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
- 可选：从 T01–T21 填入已有用例；页面会显示类别、前 60 秒期望、风险窗口、录音策略和说明
- 中文用例会自动切到中文音色
- 已改过文案再换用例时会先确认，避免误覆盖
- 合成后显示实际时长，并对照 `target_duration_s` / 风险窗口是否达标；不达标会标红，不要直接拿去评 AI
- 可切换音色、语速，合成后直接试听或下载 MP3
- 文本上限 8000 字符；页面和接口都会校验
- 预设只有在文案、音色和正常语速均未改动时，才会显示自动时长验收。自行修改后会明确提示人工确认时序。
- 文件名支持中文下载；服务端会清理不安全字符。

默认音色是 `en-US-AriaNeural`。用例文案在 `presets.json` 中维护。

## 运行质量检查

依赖已固定版本。修改服务或预设后，可运行：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q web_app.py
```

服务端对合成设置了 45 秒超时、最多 2 个并发任务和 5 秒排队时间；任务过多时会返回可重试提示。

## 标注约定

- `expected`：只针对 **前 60 秒提交给 AI** 的判断（`Risk` / `Normal`），对应 `expected_scope: first_60s`
- `risk_window`：风险话术预定出现的时间；`n/a` 表示无时序要求
- `target_duration_s`：合成后时长必须达到的下限，否则窗口可能错位
- `recording_policy`：
  - `content_only`：只测内容分类
  - `keep_first_60s`：AI 判正常后应停录，最终只保留前 60 秒
  - `record_until_end`：AI 判有风险后应继续录到挂断

T12–T18 依赖朗读时长。Edge TTS 的实际语速会随环境变化，**不会**保证刚好落在 20s / 40s / 60s。需要卡边界时，生成后查看实际时长，再微调文案或改用「较慢」语速。

## 用例一览

| ID | 类别 | 前 60 秒 | 窗口 | 录音策略 |
| --- | --- | --- | --- | --- |
| T01 | 恐怖主义 | Risk | 0-60s | 仅内容 |
| T02 | 恐怖主义（公共场所袭击） | Risk | 0-60s | 仅内容 |
| T03 | 恐怖主义新闻讨论（易误报） | Normal | n/a | 仅内容 |
| T04 | 恐怖主义历史讨论（易误报） | Normal | n/a | 仅内容 |
| T05 | 金融诈骗（索要验证码） | Risk | 0-60s | 仅内容 |
| T06 | 金融诈骗（转账/冻户） | Risk | 0-60s | 仅内容 |
| T07 | 金融诈骗（冒充警察） | Risk | 0-60s | 仅内容 |
| T08 | 金融诈骗（虚假投资） | Risk | 0-60s | 仅内容 |
| T09 | 正常银行业务 | Normal | n/a | 仅内容 |
| T10 | 反诈讨论（易误报） | Normal | n/a | 仅内容 |
| T11 | 恐怖主义 + 金融诈骗 | Risk | 0-60s | 仅内容 |
| T12 | 20s 分段：风险在 0–20s | Risk | 0-20s | 仅内容 |
| T13 | 20s 分段：风险在 20–40s | Risk | 20-40s | 仅内容 |
| T14 | 20s 分段：风险在 40–60s | Risk | 40-60s | 仅内容 |
| T15 | 20s 跨段：指令被切开 | Risk | 20-40s | 仅内容 |
| T16 | 时序：风险出现在 60s 之后 | Normal | >60s | 只留前 60s |
| T17 | 录音：全程正常的长通话 | Normal | n/a | 只留前 60s |
| T18 | 录音：开头有风险并持续说话 | Risk | 0-20s | 录到结束 |
| T19 | 恐怖主义（中文） | Risk | 0-60s | 仅内容 |
| T20 | 金融诈骗（中文） | Risk | 0-60s | 仅内容 |
| T21 | 新闻/反诈转述（中文误报） | Normal | n/a | 仅内容 |

T16 把诈骗放在 60 秒之后：前 60 秒应判 Normal；若系统仍把后段录下来，说明「只保留前 60 秒」未生效。

T15 的第一段以未说完的 `complete the` 结尾，单段不像完整诈骗；与下一段拼成 `complete the transfer of ten thousand dollars...` 后应判风险。

## 项目结构

```
web_app.py      # 网页服务
static/         # 页面、样式、前端脚本
presets.json    # T01–T21 用例文案与标注
requirements.txt
README.md
```
