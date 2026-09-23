"""Retrieve public literature evidence, without installing any tools/packages."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import subprocess
import requests
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent / "literature_evidence"
OUT.mkdir(exist_ok=True)
SOURCES = {
    "dorling_crossref": "https://api.crossref.org/works/10.1109/TSMC.2016.2582745",
    "dorling_author_manuscript": "https://arxiv.org/html/1608.02305v1",
    "zeng_crossref": "https://api.crossref.org/works/10.1109/TWC.2019.2902559",
    "zeng_author_manuscript": "https://arxiv.org/html/1804.02238",
    "zhang_crossref": "https://api.crossref.org/works/10.1109/TWC.2020.3037916",
    "zhang_author_manuscript": "https://arxiv.org/html/1912.00021",
    "twc_letpub": "https://www.letpub.com.cn/index.php?page=journalapp&view=detail&journalid=3428",
    "tsmc_letpub": "https://www.letpub.com.cn/index.php?page=journalapp&view=detail&journalid=9471",
    "stolaroff_crossref": "https://api.crossref.org/works/10.1038/s41467-017-02411-5",
    "stolaroff_publisher": "https://www.nature.com/articles/s41467-017-02411-5",
    "nature_communications_letpub": "https://www.letpub.com.cn/index.php?page=journalapp&view=detail&journalid=8411",
    "task_ref_01_xinhua": "https://www.xinhuanet.com/politics/20260709/acf8e4b353304bb78007d8224f1cd2ef/c.html",
    "task_ref_02_xinhua": "https://www.news.cn/local/20260712/8bd1f64af3124569b5cf4415fc013acd/c.html",
    "task_ref_03_copernicus": "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
    "task_ref_05_crossref": "https://api.crossref.org/works/10.1016/j.trd.2020.102668",
    "task_ref_06_itu": "https://www.itu.int/rec/R-REC-P.525-5-202411-I/en",
    "task_ref_07_ti": "https://www.ti.com/lit/an/slaa287b/slaa287b.pdf",
    "task_ref_08_crossref": "https://api.crossref.org/works/10.1109/MCOM.2016.7470933",
    "task_ref_09_dji": "https://enterprise.dji.com/matrice-350-rtk/specs",
    "task_ref_10_doodle": "https://doodlelabs.com/news/sense-interference-avoidance-release/",
    "task_ref_06_itu_pdf": "https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.525-5-202411-I!!PDF-E.pdf",
    "task_ref_08_author_manuscript": "https://arxiv.org/html/1602.03602",
    "task_ref_05_corrigendum_crossref": "https://api.crossref.org/works/10.1016/j.trd.2023.103609",
    "task_ref_05_umsl_abstract": "https://profiles.umsl.edu/en/publications/energy-consumption-models-for-delivery-drones-a-comparison-and-as/",
    "task_ref_05_trid_abstract": "https://trid.trb.org/view/1761397",
    "task_ref_05_umsl_corrigendum": "https://profiles.umsl.edu/en/publications/corrigendum-to-energy-consumption-models-for-delivery-drones-a-co/",
    "trd_letpub": "https://www.letpub.com.cn/index.php?page=journalapp&view=detail&journalid=7904",
}


def fetch(item):
    name, url = item
    try:
        response = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        response.encoding = response.apparent_encoding if "letpub" in name else "utf-8"
        if response.content.startswith(b"%PDF"):
            path = OUT / (name + ".pdf")
            path.write_bytes(response.content)
            textpath = path.with_suffix(".txt")
            subprocess.run([r"E:\tool\texlive\2025\bin\windows\pdftotext.exe", "-layout", str(path), str(textpath)], check=True)
            content = textpath.read_text(encoding="utf-8")
            suffix = ".txt"
        elif "crossref" in name:
            content = json.dumps(response.json(), ensure_ascii=False, indent=2)
            suffix = ".json"
        else:
            soup = BeautifulSoup(response.text, "html.parser")
            # LetPub contains hidden numbers. Strip all hidden elements before
            # interpreting the CAS table; JCR and other ranking tables are separate.
            for elem in soup.select("script,style,[hidden]"):
                elem.decompose()
            for elem in reversed(soup.find_all(style=True)):
                if elem.attrs and "display:none" in elem.get("style", "").replace(" ", "").lower():
                    elem.decompose()
            content = soup.get_text("\n", strip=True)
            suffix = ".txt"
        path = OUT / (name + suffix)
        path.write_text(content, encoding="utf-8")
        return {"name": name, "url": url, "resolved_url": response.url,
                "status": response.status_code, "retrieved_date": "2026-09-23",
                "file": path.name, "sha256": hashlib.sha256(content.encode()).hexdigest()}
    except Exception as exc:
        return {"name": name, "url": url, "error": str(exc)}


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, SOURCES.items()))
    (OUT / "sources.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
