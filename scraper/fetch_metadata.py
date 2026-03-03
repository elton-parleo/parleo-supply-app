import json
import requests
from bs4 import BeautifulSoup

def fetch_metadata(url: str, max_chars: int = 40000) -> str:
    """
    Fetch webpage and return:
      - full JSON-LD block where @type == Product or ProductGroup
      - otherwise fallback to cleaned page text
    """

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # -------------------------------------------------
    # 1. Try JSON-LD structured product metadata (BEST)
    # -------------------------------------------------
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        # JSON-LD sometimes returns list or dict
        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if isinstance(obj, dict):
                t = obj.get("@type", "")
                if t in ("Product", "ProductGroup"):
                    # return entire structured block
                    return json.dumps(obj, indent=2)[:max_chars]

    # -------------------------------------------------
    # 2. Fallback to generic text extraction
    # -------------------------------------------------
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    return text[:max_chars]

"""if __name__ == "__main__":
    test_url = "https://www.sephora.com/shop/gifts"
    metadata = fetch_metadata(test_url)
    print(metadata)"""