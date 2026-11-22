# 问答搜索（免费版 Perplexity 平替）

联网搜索 + 带出处引用的 AI 回答，不限次数，不用会员，不用 API Key。

- 搜索层：SearXNG 公共实例池 + Bing/DDG/Mojeek 兜底，多引擎交错去重
- 模型层：默认走免费匿名模型接口；如设置环境变量 `GEMINI_API_KEY` 或 `OPENROUTER_API_KEY`，优先用对应免费层
- 模式：快速（用摘要）/ 深度（抓取前几条正文，更准）
- 中文问题自动补一条英文搜索，资料更全

## 部署（Render 免费版）

本仓库带 `render.yaml`，在 Render 选 New Web Service 连接本仓库即可：
build `pip install -r requirements.txt`，start `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`，健康检查 `/health`。

## 本地运行

```bash
pip install -r requirements.txt
python app.py  # http://localhost:8000
```
