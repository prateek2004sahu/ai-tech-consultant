import re, httpx
from bs4 import BeautifulSoup

H = {"User-Agent": "AITechConsultantBot/1.0"}
sm = httpx.get("https://support.brilliantdirectories.com/support/sitemap.xml", headers=H, follow_redirects=True, timeout=30).text
urls = re.findall(r"<loc>(.*?)</loc>", sm)
kinds = {}
for u in urls:
    k = "articles" if "/articles/" in u else "folders" if "/folders/" in u else "other"
    kinds[k] = kinds.get(k, 0) + 1
print("total urls:", len(urls), kinds)
arts = [u for u in urls if "/articles/" in u]
print("first articles:", arts[:3])

if arts:
    u = arts[0]
    html = httpx.get(u, headers=H, follow_redirects=True, timeout=30).text
    print("\nARTICLE:", u, "| bytes:", len(html))
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    rows = []
    for el in soup.find_all(["div", "section", "article", "main"]):
        txt = sum(len(p.get_text(" ", strip=True)) for p in el.find_all(["p", "li"]))
        rows.append((txt, el.name, el.get("id"), el.get("class")))
    rows.sort(key=lambda r: -r[0])
    print("containers with the most paragraph text:")
    for r in rows[:10]:
        print(r)
    print("img count:", len(soup.find_all("img")))
    print("sample img srcs:", [i.get("src") for i in soup.find_all("img")[:4]])

