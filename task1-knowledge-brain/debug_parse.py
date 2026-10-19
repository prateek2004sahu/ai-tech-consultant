import sqlite3, httpx
from app.parse import parse_article

c = sqlite3.connect("data/kb.sqlite")
print("--- failed pages ---")
for u, e in c.execute("select url, error from pages where status='failed'"):
    print(u, "->", e)

rows = c.execute("select url, title from pages where status='done' limit 3").fetchall()
for u, t in rows:
    print("\n=== ", u, "| stored title:", t)
    r = httpx.get(u, follow_redirects=True, headers={"User-Agent": "AITechConsultantBot/1.0"}, timeout=30)
    print("HTTP", r.status_code, "| bytes", len(r.text), "| content-type", r.headers.get("content-type"))
    a = parse_article(r.text, u)
    print("sections:", len(a["sections"]), "| text chars:", sum(len(s["text"]) for s in a["sections"]))
    print("HTML start:", r.text[:600].replace("\n", " "))
    print("has <article>:", "<article" in r.text, "| has <main>:", "<main" in r.text, "| has <script>:", r.text.count("<script"))