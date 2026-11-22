import os, re, json, time, html
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
S = requests.Session(); S.headers.update(UA)

# ---------- search layer (no key needed) ----------
SEARXNG_POOL = [
    "https://search.lumy.live",
    "https://opnxng.com",
    "https://searxng.site",
    "https://priv.au",
    "https://baresearch.org",
    "https://search.bus-hit.me",
    "https://etsi.me",
    "https://searx.be",
]
_cache = {}

def search_searxng(q, n):
    key = ("sx", q, n)
    if key in _cache and time.time() - _cache[key][0] < 600:
        return _cache[key][1]
    for base in SEARXNG_POOL:
        try:
            r = S.get(base + "/search", params={"q": q, "format": "json", "language": "auto"}, timeout=10)
            if r.status_code != 200: continue
            res = r.json().get("results", [])
            out = [{"title": x.get("title", ""), "url": x.get("url", ""),
                    "snippet": (x.get("content") or "")[:400]} for x in res if x.get("url")]
            if len(out) >= 3:
                _cache[key] = (time.time(), out[:n])
                return out[:n]
        except Exception:
            continue
    return []
def clean_url(u):
    if u.startswith("//"): u = "https:" + u
    p = urlparse(u)
    if p.netloc.endswith("duckduckgo.com") and p.path.startswith("/l/"):
        q = parse_qs(p.query).get("uddg", [""])[0]
        if q: return unquote(q)
    if p.netloc.endswith("bing.com") and "/ck/" in p.path:
        import base64
        q = parse_qs(p.query).get("u", [""])[0]
        if q.startswith("a1"):
            try:
                pad = "=" * (-len(q[2:]) % 4)
                return base64.urlsafe_b64decode(q[2:] + pad).decode("utf-8", "ignore")
            except Exception:
                pass
    return u

def search_bing(q, n):
    out = []
    r = S.get("https://www.bing.com/search?q=" + quote_plus(q) + "&setlang=zh-CN", timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for li in soup.select("li.b_algo")[:n]:
        a = li.select_one("h2 a")
        if not a: continue
        sn = li.select_one(".b_caption p")
        out.append({"title": a.get_text(" ", strip=True), "url": clean_url(a.get("href", "")),
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
    return out

def search_ddg(q, n):
    out = []
    r = S.get("https://html.duckduckgo.com/html/?q=" + quote_plus(q), timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for res in soup.select(".result")[:n]:
        a = res.select_one(".result__a")
        if not a: continue
        sn = res.select_one(".result__snippet")
        out.append({"title": a.get_text(" ", strip=True), "url": clean_url(a.get("href", "")),
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
    return out

def search_mojeek(q, n):
    out = []
    r = S.get("https://www.mojeek.com/search?q=" + quote_plus(q), timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    for res in soup.select("ul.results-standard li")[:n]:
        a = res.select_one("a.title")
        if not a: continue
        sn = res.select_one("p.s")
        out.append({"title": a.get_text(" ", strip=True), "url": a.get("href", ""),
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
    return out

def search_web(q, n=8):
    lists = []
    for fn in (search_searxng, search_bing, search_ddg, search_mojeek):
        try: lists.append(fn(q, n))
        except Exception: lists.append([])
    seen, domcount, out = set(), {}, []
    for rank in range(n):
        for lst in lists:
            if len(out) >= n: break
            if rank >= len(lst): continue
            item = lst[rank]; u = item["url"]
            if not u.startswith("http") or u in seen: continue
            dom = urlparse(u).netloc
            if domcount.get(dom, 0) >= 2: continue
            seen.add(u); domcount[dom] = domcount.get(dom, 0) + 1
            out.append(item)
    return out

def fetch_text(url, limit=3500):
    try:
        r = S.get(url, timeout=12)
        if "text/html" not in r.headers.get("Content-Type", ""): return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "footer", "header", "form"]): t.decompose()
        txt = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return txt[:limit]
    except Exception:
        return ""

# ---------- LLM layer (free; key-based providers take priority if configured) ----------
def llm(messages):
    gk = os.environ.get("GEMINI_API_KEY", "")
    if gk:
        prompt = "\n\n".join(m["content"] for m in messages)
        r = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + gk,
                          json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=90)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    ok = os.environ.get("OPENROUTER_API_KEY", "")
    if ok:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": "Bearer " + ok},
                          json={"model": "openai/gpt-oss-120b:free", "messages": messages}, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    # Anonymous free endpoint, no key required
    r = requests.post("https://text.pollinations.ai/openai",
                      json={"model": "openai-fast", "messages": messages}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

SYS = """你是一个AI搜索引擎，像Perplexity一样工作。根据下面给出的联网搜索资料回答用户问题。
规则：
1. 用中文回答（用户用英文提问时用英文）。
2. 每个关键事实后面标注来源编号，格式 [1] [2]，编号对应资料列表。
3. 先给结论，再展开；结构清晰，可用小标题和列表；不要编造资料里没有的数据。综合多个来源互相印证后再下结论；只要任一来源给出了具体数字或事实，就要采用并标注，不要轻易说“没有明确说明”。
4. 回答末尾另起一行写 ---FOLLOWUPS---，然后给出3个用户可能想追问的问题，每行一个，不要编号。
"""

@app.post("/api/ask")
def ask():
    d = request.get_json(force=True)
    q = (d.get("query") or "").strip()
    mode = d.get("mode") or "quick"
    history = d.get("history") or []
    if not q: return jsonify({"error": "empty query"}), 400
    n = 8 if mode == "deep" else 6
    sources = search_web(q, n)
    queries = [q]
    if len(sources) < 5 and re.search(r"[一-鿿]", q):
        try:
            en = llm([{"role": "user", "content": "Translate this Chinese search question into a concise English web search query. Output only the query:\n" + q}])
            en = en.strip().strip('"')[:120]
            if en and not re.search(r"[一-鿿]", en): queries.append(en)
        except Exception:
            pass
    if len(queries) > 1:
        extra = search_web(queries[1], n)
        seen = {s["url"] for s in sources}
        merged = []
        for i in range(max(len(sources), len(extra))):
            if i < len(sources): merged.append(sources[i])
            if i < len(extra) and extra[i]["url"] not in seen:
                merged.append(extra[i]); seen.add(extra[i]["url"])
        sources = merged[: n + 2]
    if not sources: return jsonify({"error": "搜索没有返回结果，请换个问法再试"}), 502
    ctx = []
    for i, s in enumerate(sources, 1):
        body = s["snippet"]
        if mode == "deep" and i <= 4:
            t = fetch_text(s["url"])
            if t: body = t
        ctx.append(f"[{i}] {s['title']}\n链接：{s['url']}\n内容：{body}")
    hist_txt = ""
    for h in history[-4:]:
        hist_txt += f"用户：{h.get('q','')}\n助手：{h.get('a','')[:400]}\n"
    user_msg = (f"对话历史：\n{hist_txt}\n" if hist_txt else "") + f"用户问题：{q}\n\n搜索资料：\n" + "\n\n".join(ctx)
    try:
        raw = llm([{"role": "system", "content": SYS}, {"role": "user", "content": user_msg}])
    except Exception as e:
        return jsonify({"error": "模型调用失败，请稍后再试", "detail": str(e)[:200]}), 502
    followups = []
    if "---FOLLOWUPS---" in raw:
        raw, tail = raw.split("---FOLLOWUPS---", 1)
        followups = [x.strip("-• \t") for x in tail.strip().splitlines() if x.strip()][:3]
    for i, s in enumerate(sources, 1): s["id"] = i
    return jsonify({"answer": raw.strip(), "sources": sources, "followups": followups})

@app.get("/health")
def health(): return {"ok": True}

@app.get("/")
def index(): return Response(PAGE, mimetype="text/html")

PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>问答搜索 · 免费版</title>
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0f1113;color:#e8e9ea}
.wrap{max-width:820px;margin:0 auto;padding:20px 16px 120px}
h1.logo{font-size:26px;font-weight:600;text-align:center;margin:38px 0 6px}
.sub{text-align:center;color:#9aa0a3;font-size:13px;margin-bottom:22px}
.box{display:flex;gap:8px;background:#1c1f22;border:1px solid #2c3033;border-radius:16px;padding:10px}
.box textarea{flex:1;background:none;border:0;outline:0;color:#fff;font-size:16px;resize:none;height:44px;font-family:inherit}
.box button{background:#2f7f76;color:#fff;border:0;border-radius:12px;padding:0 18px;font-size:15px;cursor:pointer}
.modes{display:flex;gap:8px;justify-content:center;margin:12px 0 4px}
.modes span{font-size:13px;color:#9aa0a3;border:1px solid #2c3033;padding:5px 14px;border-radius:999px;cursor:pointer}
.modes span.on{color:#7fd1c5;border-color:#2f7f76}
.qa{margin-top:26px}.q{font-size:19px;font-weight:600;margin:18px 0 10px}
.a{line-height:1.75;font-size:15.5px}.a a{color:#7fd1c5;text-decoration:none}
.a sup a{background:#232629;border-radius:6px;padding:0 5px;font-size:11px}
.srcs{display:flex;gap:8px;overflow-x:auto;padding:6px 0 2px}
.src{min-width:180px;max-width:220px;background:#1c1f22;border:1px solid #2c3033;border-radius:12px;padding:9px 11px;font-size:12.5px}
.src b{display:block;font-size:13px;margin-bottom:4px;color:#e8e9ea}
.src span{color:#9aa0a3;word-break:break-all}
.src a{text-decoration:none}
.fu{display:flex;flex-direction:column;gap:6px;margin-top:14px}
.fu button{text-align:left;background:none;border:1px solid #2c3033;color:#c9ccce;border-radius:10px;padding:9px 12px;font-size:14px;cursor:pointer}
.load{color:#9aa0a3;font-size:14px;margin-top:16px}
.err{color:#ff9c9c;font-size:14px;margin-top:16px}
</style></head><body><div class="wrap">
<h1 class="logo">问答搜索</h1><div class="sub">免费版 · 联网搜索 + 带出处回答 · 不限次数</div>
<div class="box"><textarea id="q" placeholder="想问什么都可以…"></textarea><button id="go">搜索</button></div>
<div class="modes"><span id="mq" class="on">快速</span><span id="md">深度（抓正文，更准更慢）</span></div>
<div id="out"></div></div>
<script>
let mode='quick',hist=[];
const out=document.getElementById('out'),qEl=document.getElementById('q');
mq.onclick=()=>{mode='quick';mq.classList.add('on');md.classList.remove('on')};
md.onclick=()=>{mode='deep';md.classList.add('on');mq.classList.remove('on')};
function cite(md,srcs){return md.replace(/\[(\d+)\]/g,(m,n)=>{const s=srcs[n-1];return s?`<sup><a href="${s.url}" target="_blank">${n}</a></sup>`:m})}
async function ask(q){
 if(!q.trim())return; qEl.value='';
 const div=document.createElement('div');div.className='qa';
 div.innerHTML=`<div class="q">${q.replace(/</g,'&lt;')}</div><div class="load">正在联网搜索并整理答案…</div>`;
 out.prepend(div); const load=div.querySelector('.load');
 try{
  const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q,mode,history:hist})});
  const d=await r.json(); if(d.error){load.className='err';load.textContent=d.error;return}
  hist.push({q,a:d.answer});
  const srcHtml=d.sources.map(s=>`<div class="src"><a href="${s.url}" target="_blank"><b>${s.id}. ${s.title.replace(/</g,'&lt;')}</b><span>${new URL(s.url).hostname}</span></a></div>`).join('');
  load.outerHTML=`<div class="srcs">${srcHtml}</div><div class="a">${marked.parse(cite(d.answer,d.sources))}</div>`+
   (d.followups.length?`<div class="fu">${d.followups.map(f=>`<button>${f.replace(/</g,'&lt;')}</button>`).join('')}</div>`:'');
  div.querySelectorAll('.fu button').forEach(b=>b.onclick=()=>ask(b.textContent));
 }catch(e){load.className='err';load.textContent='请求失败，请再试一次'}
}
go.onclick=()=>ask(qEl.value);
qEl.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(qEl.value)}});
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
