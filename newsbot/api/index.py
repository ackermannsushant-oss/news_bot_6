"""
PressAI — Multi-source Indian News AI
Sources: The Hindu, DD News, Firstpost, TOI, ET, Jagran, Bhaskar, ANI
"""
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from bs4 import BeautifulSoup
from datetime import datetime
import requests, time, os

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app   = Flask(__name__, template_folder=os.path.join(_root,"templates"), static_folder=os.path.join(_root,"static"))
CORS(app)

# ── Config ─────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
CACHE_TTL    = 600

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Sources ─────────────────────────────────────────────────────
SOURCES = {
    "thehindu":  {"name":"The Hindu",       "base":"https://www.thehindu.com",             "selectors":["div.story-card","div.element","article","div.storylist-element"],   "kw":"/article"},
    "ddnews":    {"name":"DD News",          "base":"https://ddnews.gov.in",                "selectors":["div.views-row","article",".news-item","div.view-content > div"],     "kw":"/en/"},
    "firstpost": {"name":"Firstpost",        "base":"https://www.firstpost.com",            "selectors":["div.article-list-item","article",".story-box","div.listicle-item"], "kw":"/firstpost/"},
    "toi":       {"name":"Times of India",   "base":"https://timesofindia.indiatimes.com",  "selectors":["div.col_l_6","div.uwU81","article","div.list_item"],                 "kw":"articleshow"},
    "et":        {"name":"Economic Times",   "base":"https://economictimes.indiatimes.com", "selectors":["div.eachStory","article","div.story-box","li.clearfix"],             "kw":"articleshow"},
    "jagran":    {"name":"Jagran",           "base":"https://www.jagran.com",               "selectors":["div.article-list","article","li.list-news","div.news-item"],         "kw":"/news/"},
    "bhaskar":   {"name":"Dainik Bhaskar",   "base":"https://www.bhaskar.com",              "selectors":["div.story-list","article","div.leading-news","div.card"],            "kw":"/news/"},
    "ani":       {"name":"ANI News",         "base":"https://aninews.in",                   "selectors":["div.content-block","article","div.news-card","div.col-md-4"],        "kw":"/news/"},
}

CATEGORIES = {
    "top":         {"label":"Top News",      "urls":{"thehindu":"https://www.thehindu.com/","ddnews":"https://ddnews.gov.in/en/","firstpost":"https://www.firstpost.com/","toi":"https://timesofindia.indiatimes.com/","ani":"https://aninews.in/"}},
    "national":    {"label":"National",      "urls":{"thehindu":"https://www.thehindu.com/news/national/","ddnews":"https://ddnews.gov.in/en/category/national/","firstpost":"https://www.firstpost.com/india/","toi":"https://timesofindia.indiatimes.com/india","ani":"https://aninews.in/topic/india/"}},
    "international":{"label":"World",        "urls":{"thehindu":"https://www.thehindu.com/news/international/","firstpost":"https://www.firstpost.com/world/","toi":"https://timesofindia.indiatimes.com/world","ani":"https://aninews.in/topic/world/"}},
    "business":    {"label":"Business",      "urls":{"thehindu":"https://www.thehindu.com/business/","et":"https://economictimes.indiatimes.com/","firstpost":"https://www.firstpost.com/business/","toi":"https://timesofindia.indiatimes.com/business"}},
    "sport":       {"label":"Sports",        "urls":{"thehindu":"https://www.thehindu.com/sport/","firstpost":"https://www.firstpost.com/sports/","toi":"https://timesofindia.indiatimes.com/sports","ddnews":"https://ddnews.gov.in/en/category/sports/"}},
    "technology":  {"label":"Tech",          "urls":{"thehindu":"https://www.thehindu.com/sci-tech/technology/","firstpost":"https://www.firstpost.com/tech/","et":"https://economictimes.indiatimes.com/tech","toi":"https://timesofindia.indiatimes.com/technology"}},
    "entertainment":{"label":"Entertainment","urls":{"thehindu":"https://www.thehindu.com/entertainment/","firstpost":"https://www.firstpost.com/entertainment/","toi":"https://timesofindia.indiatimes.com/entertainment"}},
    "health":      {"label":"Health",        "urls":{"thehindu":"https://www.thehindu.com/sci-tech/health/","firstpost":"https://www.firstpost.com/health/","toi":"https://timesofindia.indiatimes.com/life-style/health-fitness","ddnews":"https://ddnews.gov.in/en/category/health/"}},
    "science":     {"label":"Science",       "urls":{"thehindu":"https://www.thehindu.com/sci-tech/science/","firstpost":"https://www.firstpost.com/science/","ddnews":"https://ddnews.gov.in/en/category/science/"}},
    "hindi":       {"label":"Hindi News",    "urls":{"jagran":"https://www.jagran.com/","bhaskar":"https://www.bhaskar.com/"}},
    "environment": {"label":"Environment",   "urls":{"thehindu":"https://www.thehindu.com/sci-tech/energy-and-environment/","ddnews":"https://ddnews.gov.in/en/category/environment/"}},
}

_cache: dict[str, tuple[list, float]] = {}


# ── Scraper ─────────────────────────────────────────────────────
def scrape_url(url: str, src_key: str, limit: int = 8) -> list[dict]:
    if url in _cache and time.time() < _cache[url][1]:
        return _cache[url][0]

    src = SOURCES.get(src_key, SOURCES["thehindu"])
    base, articles, seen = src["base"], [], set()

    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for sel in src["selectors"]:
            for item in soup.select(sel):
                if len(articles) >= limit: break
                hl = item.select_one("h1,h2,h3,h4")
                if not hl: continue
                headline = hl.get_text(strip=True)
                a_tag    = item.find("a", href=True) or hl.find("a", href=True)
                link     = a_tag["href"] if a_tag else ""
                if link and not link.startswith("http"): link = base + link
                if not link or link in seen or len(headline) < 12: continue
                seen.add(link)
                s_el = item.select_one("p.intro,p.summary,.synopsis,p")
                p_el = item.select_one("time,.date,.dateline,span.time,.timestamp")
                articles.append({
                    "headline":  headline,
                    "summary":   s_el.get_text(strip=True)[:200] if s_el else "",
                    "link":      link,
                    "published": p_el.get_text(strip=True)[:40] if p_el else "",
                    "source":    src["name"],
                })

        if len(articles) < 3:
            for a in soup.find_all("a", href=True):
                if len(articles) >= limit: break
                href, text = a["href"], a.get_text(strip=True)
                if len(text) > 15 and src["kw"] in href and href not in seen:
                    seen.add(href)
                    articles.append({"headline":text,"summary":"","published":"","link":href if href.startswith("http") else base+href,"source":src["name"]})

    except Exception as e:
        print(f"[Scraper] {src_key} {url}: {e}")

    _cache[url] = (articles, time.time() + CACHE_TTL)
    return articles


def get_category_articles(category: str, limit_per: int = 6) -> list[dict]:
    cat_data = CATEGORIES.get(category, CATEGORIES["top"])
    all_arts, seen_h = [], set()
    for sk, url in cat_data["urls"].items():
        for a in scrape_url(url, sk, limit_per):
            key = a["headline"][:50].lower()
            if key not in seen_h:
                seen_h.add(key)
                all_arts.append(a)
    return all_arts


# ── AI Layer ─────────────────────────────────────────────────────
def build_context(category: str) -> str:
    articles = get_category_articles(category)
    cat_label = CATEGORIES.get(category, {}).get("label", category.upper())
    sources_used = list({a["source"] for a in articles})
    lines = [
        f"## LIVE NEWS FEED — {cat_label.upper()}",
        f"## {datetime.now().strftime('%A, %d %B %Y, %H:%M IST')}",
        f"## Sources active: {', '.join(sources_used)}", "",
    ]
    for i, a in enumerate(articles, 1):
        lines += [f"**[{a['source']}] #{i}** {a['headline']}"]
        if a["summary"]:   lines.append(f"  > {a['summary']}")
        if a["published"]: lines.append(f"  📅 {a['published']}")
        lines += [f"  🔗 {a['link']}", ""]
    return "\n".join(lines)


def call_groq(system: str, messages: list[dict]) -> str:
    if not GROQ_API_KEY:
        return "⚠️ **GROQ_API_KEY not set.**\n\nAdd it in:\n- **Vercel**: Project → Settings → Environment Variables\n- **Local**: `export GROQ_API_KEY=your_key`\n\nGet free key at https://console.groq.com"

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model":GROQ_MODEL,"messages":[{"role":"system","content":system}]+messages,"max_tokens":2048,"temperature":0.65,"stream":False},
        timeout=45,
    )
    if resp.status_code == 401: return "❌ Invalid Groq API key. Check https://console.groq.com"
    if resp.status_code == 429: return "⚠️ Rate limit hit. Please wait a moment and retry."
    if resp.status_code != 200: return f"❌ Groq error {resp.status_code}: {resp.text[:200]}"
    return resp.json()["choices"][0]["message"]["content"]


def ai_response(message: str, language: str, category: str, history: list) -> str:
    lang_rule = (
        "CRITICAL: You MUST respond entirely in Hindi (Devanagari script). Write natural, fluent Hindi only."
        if language == "hi"
        else "Respond in clear, fluent English."
    )
    system = f"""You are PressAI — an expert AI news analyst and journalist with deep expertise in Indian and global affairs. You aggregate live news from 8 trusted Indian sources: The Hindu, Times of India, Economic Times, Firstpost, DD News, ANI, Jagran, and Dainik Bhaskar.

{lang_rule}
TODAY: {datetime.now().strftime('%A, %d %B %Y')} | CATEGORY: {CATEGORIES.get(category,{}).get('label',category)}

{build_context(category)}

## YOUR CAPABILITIES:

**News Analysis:**
- Synthesize information from ALL sources above into one coherent briefing
- Go beyond headlines — provide context, background, and implications
- Compare what different sources say; highlight agreements and divergences
- Cite [Source Name] and URLs when referencing specific stories
- For breaking news, explain the "why" and "what it means"

**Deep Analytical Questions:**
- Use your full training knowledge PLUS live news above
- Explain complex topics: economic policy, geopolitics, court judgments, science, technology
- Provide historical context, expert-level analysis, cause-and-effect reasoning
- For political/policy questions: explain multiple perspectives fairly
- For economic questions: use data, trends, and expert frameworks
- Never shy away from nuanced, complex, multi-faceted answers

**General Knowledge:**
- Draw on your broad knowledge base for any topic
- Connect current news to historical patterns when relevant
- Be authoritative but acknowledge uncertainty when appropriate

**Format:**
- Use **bold** for source names, key terms, important facts
- Use numbered lists for multiple stories or points
- Use headers (##) for long multi-section answers
- For simple questions: 2-3 focused paragraphs
- For complex analysis: structured, comprehensive response with sections
- Always cite URLs for stories so users can read more

**Tone:** Senior editorial journalist — authoritative, balanced, analytical, insightful.

{lang_rule}"""

    msgs = [{"role":m["role"],"content":m["content"]} for m in history[-8:] if m.get("role") in ("user","assistant")]
    msgs.append({"role":"user","content":message})
    return call_groq(system, msgs)


# ── Routes ───────────────────────────────────────────────────────
@app.route("/")
def home(): return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    msg  = data.get("message","").strip()
    if not msg: return jsonify({"error":"Empty message"}), 400
    try:
        return jsonify({"reply":ai_response(msg,data.get("language","en"),data.get("category","top"),data.get("history",[])),"status":"ok"})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/news/<category>")
def get_news(category):
    return jsonify({"articles":get_category_articles(category,6),"category":category})

@app.route("/api/categories")
def categories():
    return jsonify({"categories":{k:v["label"] for k,v in CATEGORIES.items()}})

@app.route("/health")
def health():
    return jsonify({"status":"ok","time":datetime.now().isoformat(),"model":GROQ_MODEL,"sources":list(SOURCES.keys()),"api_key":"✅ Set" if GROQ_API_KEY else "❌ Missing"})

if __name__ == "__main__":
    print(f"\n  📡 PressAI  |  {GROQ_MODEL}  |  http://localhost:5030\n")
    app.run(debug=True, host="0.0.0.0", port=5030)
