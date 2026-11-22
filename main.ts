// Mikie Search — free Perplexity-style AI search (Deno Deploy)
// Search: SearXNG public pool + Bing fallback. LLM: free anonymous model endpoint.
const UA = { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8" };

let PAGE = "<h1>问答搜索</h1>";
try { PAGE = await Deno.readTextFile(new URL("./index.html", import.meta.url)); } catch (_) { /* fallback */ }

const SEARXNG_POOL = [
  "https://search.lumy.live", "https://opnxng.com", "https://searxng.site",
  "https://priv.au", "https://baresearch.org", "https://search.bus-hit.me",
  "https://etsi.me", "https://searx.be",
];
const cache = new Map();

async function searchSearxng(q, n) {
  const key = "sx|" + q + "|" + n;
  const hit = cache.get(key);
  if (hit && Date.now() - hit[0] < 600000) return hit[1];
  for (const base of SEARXNG_POOL) {
    try {
      const r = await fetch(base + "/search?q=" + encodeURIComponent(q) + "&format=json&language=auto", { headers: UA, signal: AbortSignal.timeout(10000) });
      if (!r.ok) continue;
      const j = await r.json();
      const out = (j.results || []).filter((x) => x.url).map((x) => ({ title: x.title || "", url: x.url, snippet: (x.content || "").slice(0, 400) }));
      if (out.length >= 3) { cache.set(key, [Date.now(), out.slice(0, n)]); return out.slice(0, n); }
    } catch (_) { continue; }
  }
  return [];
}

function bingDecode(u) {
  try {
    const p = new URL(u);
    if (p.hostname.endsWith("bing.com") && p.pathname.includes("/ck/")) {
      const q = p.searchParams.get("u") || "";
      if (q.startsWith("a1")) return atob(q.slice(2).replace(/-/g, "+").replace(/_/g, "/"));
    }
  } catch (_) {}
  return u;
}

async function searchBing(q, n) {
  const out = [];
  const r = await fetch("https://www.bing.com/search?q=" + encodeURIComponent(q) + "&setlang=zh-CN", { headers: UA, signal: AbortSignal.timeout(15000) });
  const html = await r.text();
  const blocks = html.split('<li class="b_algo"').slice(1, n + 1);
  for (const b of blocks) {
    const m = b.match(/<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/);
    if (!m) continue;
    const sm = b.match(/<p[^>]*>([\s\S]*?)<\/p>/);
    const strip = (s) => s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    out.push({ title: strip(m[2]), url: bingDecode(m[1]), snippet: sm ? strip(sm[1]) : "" });
  }
  return out;
}

async function searchWeb(q, n) {
  const lists = [];
  lists.push(await searchSearxng(q, n).catch(() => []));
  if (lists[0].length < 3) lists.push(await searchBing(q, n).catch(() => []));
  const seen = new Set(), domCount = {}, out = [];
  for (let rank = 0; rank < n; rank++) {
    for (const lst of lists) {
      if (out.length >= n) break;
      const item = lst[rank]; if (!item) continue;
      if (!item.url.startsWith("http") || seen.has(item.url)) continue;
      const dom = new URL(item.url).hostname;
      if ((domCount[dom] || 0) >= 2) continue;
      seen.add(item.url); domCount[dom] = (domCount[dom] || 0) + 1; out.push(item);
    }
  }
  return out;
}

async function fetchText(url, limit = 3500) {
  try {
    const r = await fetch(url, { headers: UA, signal: AbortSignal.timeout(12000) });
    if (!(r.headers.get("content-type") || "").includes("text/html")) return "";
    let t = await r.text();
    t = t.replace(/<(script|style|nav|footer|header|form)[\s\S]*?<\/\1>/gi, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return t.slice(0, limit);
  } catch (_) { return ""; }
}

async function llm(messages) {
  const gk = Deno.env.get("GEMINI_API_KEY") || "";
  if (gk) {
    const prompt = messages.map((m) => m.content).join("\n\n");
    const r = await fetch("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + gk, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }), signal: AbortSignal.timeout(90000) });
    const j = await r.json();
    return j.candidates[0].content.parts[0].text;
  }
  const ok = Deno.env.get("OPENROUTER_API_KEY") || "";
  if (ok) {
    const r = await fetch("https://openrouter.ai/api/v1/chat/completions", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + ok }, body: JSON.stringify({ model: "openai/gpt-oss-120b:free", messages }), signal: AbortSignal.timeout(90000) });
    const j = await r.json();
    return j.choices[0].message.content;
  }
  const r = await fetch("https://text.pollinations.ai/openai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: "openai-fast", messages }), signal: AbortSignal.timeout(90000) });
  if (!r.ok) throw new Error("llm http " + r.status);
  const j = await r.json();
  return j.choices[0].message.content;
}

const SYS = `你是一个AI搜索引擎，像Perplexity一样工作。根据下面给出的联网搜索资料回答用户问题。
规则：
1. 用中文回答（用户用英文提问时用英文）。
2. 每个关键事实后面标注来源编号，格式 [1] [2]，编号对应资料列表。
3. 先给结论，再展开；结构清晰，可用小标题和列表；不要编造资料里没有的数据。综合多个来源互相印证后再下结论；只要任一来源给出了具体数字或事实，就要采用并标注，不要轻易说“没有明确说明”。
4. 回答末尾另起一行写 ---FOLLOWUPS---，然后给出3个用户可能想追问的问题，每行一个，不要编号。`;

async function ask(body) {
  const q = (body.query || "").trim();
  const mode = body.mode || "quick";
  const history = body.history || [];
  if (!q) return { error: "empty query" };
  const n = mode === "deep" ? 8 : 6;
  let sources = await searchWeb(q, n);
  if (sources.length < 5 && /[一-鿿]/.test(q)) {
    try {
      const en = (await llm([{ role: "user", content: "Translate this Chinese search question into a concise English web search query. Output only the query:\n" + q }])).trim().replace(/^"|"$/g, "").slice(0, 120);
      if (en && !/[一-鿿]/.test(en)) {
        const extra = await searchWeb(en, n);
        const seen = new Set(sources.map((s) => s.url));
        const merged = [];
        for (let i = 0; i < Math.max(sources.length, extra.length); i++) {
          if (sources[i]) merged.push(sources[i]);
          if (extra[i] && !seen.has(extra[i].url)) { merged.push(extra[i]); seen.add(extra[i].url); }
        }
        sources = merged.slice(0, n + 2);
      }
    } catch (_) {}
  }
  if (!sources.length) return { error: "搜索没有返回结果，请换个问法再试" };
  const ctx = [];
  for (let i = 0; i < sources.length; i++) {
    const s = sources[i];
    let content = s.snippet;
    if (mode === "deep" && i < 4) { const t = await fetchText(s.url); if (t) content = t; }
    ctx.push(`[${i + 1}] ${s.title}\n链接：${s.url}\n内容：${content}`);
  }
  let histTxt = "";
  for (const h of history.slice(-4)) histTxt += `用户：${h.q || ""}\n助手：${(h.a || "").slice(0, 400)}\n`;
  const userMsg = (histTxt ? "对话历史：\n" + histTxt + "\n" : "") + "用户问题：" + q + "\n\n搜索资料：\n" + ctx.join("\n\n");
  let raw;
  try { raw = await llm([{ role: "system", content: SYS }, { role: "user", content: userMsg }]); }
  catch (e) { return { error: "模型调用失败，请稍后再试", detail: String(e).slice(0, 200) }; }
  let followups = [];
  if (raw.includes("---FOLLOWUPS---")) {
    const parts = raw.split("---FOLLOWUPS---");
    raw = parts[0];
    followups = parts[1].trim().split("\n").map((x) => x.replace(/^[-•\s]+/, "").trim()).filter(Boolean).slice(0, 3);
  }
  sources.forEach((s, i) => s.id = i + 1);
  return { answer: raw.trim(), sources, followups };
}

Deno.serve({ port: Number(Deno.env.get("PORT") || 8000) }, async (req) => {
  const url = new URL(req.url);
  if (url.pathname === "/health") return Response.json({ ok: true });
  if (url.pathname === "/api/ask" && req.method === "POST") {
    const body = await req.json().catch(() => ({}));
    const res = await ask(body);
    return Response.json(res, { status: res.error ? (res.error === "empty query" ? 400 : 502) : 200 });
  }
  if (url.pathname === "/") return new Response(PAGE, { headers: { "content-type": "text/html; charset=utf-8" } });
  return new Response("not found", { status: 404 });
});
