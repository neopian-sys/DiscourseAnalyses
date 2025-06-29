# -*- coding: utf-8 -*-
"""Xi Jinping Speeches Analysis

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1i-mHYjlP3sx5pGiTvpDMYm1PUU5Gb647
"""

# 🟩 CELL 1: Install & pin all dependencies in one go
!pip install --upgrade pip

# 1. Install the right numpy first (so gensim builds against it)
!pip install numpy==1.24.4

# 2. Then install gensim and everything else (they’ll pick up numpy 1.24.4)
!pip install \
    gensim \
    requests \
    beautifulsoup4 \
    tqdm \
    pkuseg \
    opencc-python-reimplemented \
    pandas \
    matplotlib \
    seaborn \
    networkx \
    scikit-learn \
    jieba

# 🟩 CELL 2: Imports and Configuration
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
import pandas as pd
import jieba
import pkuseg
from opencc import OpenCC              # ← add this
from collections import Counter, defaultdict
from gensim import corpora, models
import matplotlib.pyplot as plt
import seaborn as sns

# Config
BASE_URL   = "https://jhsjk.people.cn/"
KEYWORDS   = ["科研伦理", "科技伦理", "人工智能向善", "科技向善", "守正创新", "负责人创新", "高水平安全", "科研诚信"]
SEGMENTER  = 'pkuseg'  # or 'jieba'
cc         = OpenCC('t2s')  # Traditional → Simplified

# 🟩 CELL 3: Get ALL Speech Links (full eight categories, loose regex, HTTPS, save links)
import re, time, json, os, requests
from bs4 import BeautifulSoup

# These form IDs correspond exactly to the tabs on jhsjk.people.cn:
# 701=会议, 702=活动, 703=考察, 704=会见, 705=出访, 706=讲话, 707=函电, 718=其他
ALL_FORMS = [701, 702, 703, 704, 705, 706, 707, 718]

def get_all_speech_links(forms=ALL_FORMS):
    """
    Crawl each form/category until no more results, collecting ALL '/article/<id>' links.
    Saves to 'output/links.json' so you never lose progress.
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    all_links = set()

    for form in forms:
        page = 1
        while True:
            suffix = f"&page={page}" if page > 1 else ""
            url = f"https://jhsjk.people.cn/result?else=501&form={form}{suffix}"
            print(f"Fetching form={form}, page={page}: {url}")
            try:
                res = requests.get(url, headers=headers, timeout=10)
                res.raise_for_status()
            except Exception as e:
                print(f"  [!] form={form} page {page} error: {e}")
                break

            soup = BeautifulSoup(res.text, 'html.parser')
            # match any 'article/<digits>' in the href
            anchors = soup.find_all('a', href=re.compile(r'article/\d+'))
            if not anchors:
                print(f"  [!] form={form} page {page} has no links, moving on.")
                break

            for a in anchors:
                href = a['href'].strip()
                # build full URL on the .cn host, force HTTPS
                if href.lower().startswith('http'):
                    full = href.replace('http://', 'https://')
                else:
                    full = 'https://jhsjk.people.cn' + href if href.startswith('/') else 'https://jhsjk.people.cn/' + href
                all_links.add(full)

            print(f"  [+] form={form} page {page}: +{len(anchors)} links (total {len(all_links)})")
            page += 1
            time.sleep(0.5)

    # persist links immediately
    os.makedirs('output', exist_ok=True)
    with open('output/links.json', 'w', encoding='utf-8') as f:
        json.dump(sorted(all_links), f, ensure_ascii=False, indent=2)
    print(f"[✓] Saved {len(all_links)} links to output/links.json")

    return list(all_links)

# 🟩 CELL 4: Get Speech Content (HTTPS + headers + timeout)
import re, requests
from bs4 import BeautifulSoup

def get_speech_content(url):
    """
    Fetch the speech page via HTTPS with proper headers & timeout,
    then parse out title, date, and content. Returns None on error.
    """
    url = url.replace("http://", "https://")
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://jhsjk.people.cn/'
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"[!] Failed to fetch {url}: {type(e).__name__} – {e}")
        return None

    soup = BeautifulSoup(res.text, 'html.parser')
    # 1) Title
    title_tag = soup.find('h1') or soup.find('h2') or soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else url

    # 2) Full text
    full_text = soup.get_text("\n", strip=True)

    # 3) Date via regex
    m = re.search(r'(\d{4}[年\-]\d{1,2}[月\-]\d{1,2}[日]?)', full_text)
    date_str = m.group(1) if m else ""

    # 4) Content = after title, before boilerplate
    after = full_text.split(title, 1)[-1]
    content = re.split(r'责任编辑|编辑|相关链接', after)[0].strip()

    return {"title": title, "date": date_str, "url": url, "content": content}

# 🟩 CELL 5: Preprocessing & Segmentation
# Instantiate segmenter once to avoid repeated loading
def initialize_segmenter():
    if SEGMENTER == 'pkuseg':
        return pkuseg.pkuseg()
    else:
        return jieba

# Initialize global segmenter instance
global_seg = initialize_segmenter()

# Preprocessing: convert Traditional to Simplified, keep only Chinese chars
import jieba.posseg as pseg  # optional if you need POS filtering

def preprocess_text(text):
    # Convert to Simplified Chinese
    text = cc.convert(text)
    # Remove non-Chinese characters (punctuation, Latin letters, numbers)
    text = re.sub(r"[^一-龥]", "", text)
    return text

# Segmentation: return a list of tokens
# You can also filter out stopwords here if desired
def segment_text(text):
    tokens = []
    # Use list() to realize generator
    for word in global_seg.cut(text):
        tokens.append(word)
    return tokens

# (Optional) Stopword removal example:
# STOPWORDS = set(open('stopwords.txt', encoding='utf-8').read().split())
# tokens = [w for w in tokens if w not in STOPWORDS]

# 🟩 CELL 6: Keyword Analysis
def keyword_analysis(
    speeches,
    keywords,
    start_date=None,
    end_date=None,
    top_n=10
):
    """
    Analyze keyword frequencies across speeches.

    Args:
        speeches (list of dict): Each dict has keys 'title', 'date', 'url', 'content'.
        keywords (list of str): Keywords/phrases to count.
        start_date (str or datetime, optional): Minimum date filter (inclusive).
        end_date (str or datetime, optional): Maximum date filter (inclusive).
        top_n (int): Number of top speeches to return by total mentions.

    Returns:
        summary_df (pd.DataFrame): Table with columns [Keyword, Total Mentions,
            Top Speech, Mentions in Top Speech, Top Year, Mentions in Top Year].
        top_speeches (list of tuples): [(speech_title, total_mentions), ...] sorted desc.
    """
    # Convert to DataFrame for easy filtering
    df = pd.DataFrame(speeches)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    if start_date is not None:
        df = df[df['date'] >= pd.to_datetime(start_date)]
    if end_date is not None:
        df = df[df['date'] <= pd.to_datetime(end_date)]

    # Initialize counters
    keyword_counts = Counter()
    speech_hits = {kw: Counter() for kw in keywords}
    year_hits = {kw: Counter() for kw in keywords}

    # Count occurrences per speech and per year
    for _, row in df.iterrows():
        content = row['content']
        title = row['title']
        year = row['date'].year if pd.notnull(row['date']) else None
        for kw in keywords:
            freq = content.count(kw)
            if freq > 0:
                keyword_counts[kw] += freq
                speech_hits[kw][title] += freq
                if year:
                    year_hits[kw][year] += freq

    # Build the summary table
    rows = []
    for kw in keywords:
        total = keyword_counts.get(kw, 0)
        top_speech, top_speech_count = (
            speech_hits[kw].most_common(1)[0] if speech_hits[kw] else ("None", 0)
        )
        top_year, top_year_count = (
            year_hits[kw].most_common(1)[0] if year_hits[kw] else ("None", 0)
        )
        rows.append({
            'Keyword': kw,
            'Total Mentions': total,
            'Top Speech': top_speech,
            'Mentions in Top Speech': top_speech_count,
            'Top Year': top_year,
            'Mentions in Top Year': top_year_count,
        })
    summary_df = pd.DataFrame(rows).sort_values('Total Mentions', ascending=False)

    # Compute overall top speeches across all keywords
    overall = Counter()
    for kw in keywords:
        overall.update(speech_hits[kw])
    top_speeches = overall.most_common(top_n)

    return summary_df, top_speeches

# 🟩 CELL 7: Topic Modeling & Visualization
from gensim.models import CoherenceModel

def run_topic_modeling(
    speeches,
    num_topics=5,
    passes=15,
    compute_coherence=True
):
    """
    Perform LDA topic modeling with optional coherence calculation.

    Args:
        speeches (list of dict): Each dict needs a 'content' field.
        num_topics (int): Number of LDA topics to extract.
        passes (int): Number of training passes over the corpus.
        compute_coherence (bool): If True, compute and print the c_v coherence.
    Returns:
        dict: {
            'model': the trained LdaModel,
            'corpus': list of bow vectors,
            'dictionary': the gensim Dictionary,
            'coherence': float (only if compute_coherence)
        }
    """
    print("[*] Preparing texts for LDA…")
    texts = [
        list(segment_text(preprocess_text(s["content"])))
        for s in speeches
    ]
    texts = [t for t in texts if t]  # drop empty docs

    print("[*] Building dictionary…")
    dictionary = corpora.Dictionary(texts)
    dictionary.filter_extremes(no_below=5, no_above=0.5)

    print("[*] Building corpus…")
    corpus = [dictionary.doc2bow(text) for text in texts]

    print(f"[*] Training LDA ({num_topics} topics, {passes} passes)…")
    lda_model = models.LdaModel(
        corpus=corpus,
        id2word=dictionary,
        num_topics=num_topics,
        passes=passes,
        random_state=42,
    )

    print("[*] Topics:")
    for idx, topic in lda_model.print_topics(num_words=10):
        print(f"  Topic {idx}: {topic}")

    result = {"model": lda_model, "corpus": corpus, "dictionary": dictionary}

    if compute_coherence:
        print("[*] Calculating coherence score…")
        cm = CoherenceModel(
            model=lda_model,
            texts=texts,
            dictionary=dictionary,
            coherence="c_v",
        )
        score = cm.get_coherence()
        print(f"[+] Coherence (c_v): {score:.4f}")
        result["coherence"] = score

    return result


def visualize_term_trends(
    speeches,
    keywords,
    window=1
):
    """
    Plot keyword frequency over time, with optional rolling smoothing.

    Args:
        speeches (list of dict): Each must have 'content' and parseable 'date'.
        keywords (list of str): Terms to count.
        window (int): Years to smooth over (1 = no smoothing).
    """
    print("[*] Aggregating keyword counts by year…")
    df = pd.DataFrame(speeches)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year

    # Build a year × keyword DataFrame
    yearly = (
        df.groupby("year")["content"]
          .apply(lambda texts: pd.Series({
              kw: sum(txt.count(kw) for txt in texts)
              for kw in keywords
          }))
          .unstack()
          .fillna(0)
    )

    if window > 1:
        yearly = yearly.rolling(window, min_periods=1).mean()

    plt.figure(figsize=(12, 6))
    for kw in keywords:
        plt.plot(
            yearly.index,
            yearly[kw],
            label=kw,
            marker="o",
        )
    plt.legend()
    plt.title("Keyword Frequency Over Time")
    plt.xlabel("Year")
    plt.ylabel("Frequency")
    plt.xticks(yearly.index, rotation=45)
    plt.tight_layout()
    plt.show()

# 🟩 CELL 8: Resume-capable Main Pipeline with Polite Crawling
import os
import json
import random
import time
import requests
from tqdm import tqdm
from IPython.display import display

# A small pool of realistic User-Agent strings
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Ubuntu Chromium/114.0.5735.198 Chrome/114.0.5735.198 Safari/537.36"
]

def main(
    keywords=KEYWORDS,
    start_date=None,
    end_date=None,
    num_topics=5,
    passes=15,
    output_dir="output"
):
    """
    1) Load existing raw_speeches.json if present
    2) Scrape only new URLs with retries, UA rotation, backoff, random delays
    3) Partial save of scraped speeches
    4) Save full raw_speeches.json
    5) Run keyword analysis, topic modeling, trend plots
    6) Export keyword summary to CSV/XLSX
    """
    os.makedirs(output_dir, exist_ok=True)
    raw_path = os.path.join(output_dir, "raw_speeches.json")

    # 1) Load existing data
    if os.path.exists(raw_path):
        with open(raw_path, "r", encoding="utf-8") as f:
            speeches = json.load(f)
        scraped_urls = {s["url"] for s in speeches}
        print(f"[✓] Loaded {len(speeches)} existing speeches.")
    else:
        speeches = []
        scraped_urls = set()
        print("[i] No existing speeches found; starting fresh.")

    # 2) Gather all links, filter out already scraped
    all_links = get_all_speech_links()
    to_scrape = [url for url in all_links if url not in scraped_urls]
    print(f"[✓] {len(to_scrape)} new speeches to scrape (out of {len(all_links)} total).")

    session = requests.Session()
    failures = []

    # 2a) Scrape with retries, UA rotation, backoff, random delay
    for url in tqdm(to_scrape, desc="Scraping new speeches"):
        for attempt in range(5):
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Referer": "https://jhsjk.people.cn/"
            }
            try:
                resp = session.get(url, headers=headers, timeout=10)
                resp.raise_for_status()
                sp = get_speech_content(url)  # uses HTTPS, headers & timeout internally
                if sp and sp["content"].strip():
                    sp["content"] = preprocess_text(sp["content"])
                    speeches.append(sp)
                else:
                    failures.append((url, "Empty content"))
                break  # success → exit retry loop
            except requests.HTTPError as he:
                code = resp.status_code if 'resp' in locals() else None
                if code in (403, 429):
                    wait = 10 * (2 ** attempt)
                    print(f"[!] {code} on {url}, backoff {wait}s…")
                    time.sleep(wait)
                    continue
                else:
                    failures.append((url, f"HTTPError {he}"))
                    break
            except Exception as e:
                failures.append((url, str(e)))
                break
        # polite random delay between 1–3 seconds
        time.sleep(random.uniform(1, 3))

    new_count = len(speeches) - len(scraped_urls)
    print(f"[✓] Added {new_count} new speeches, {len(failures)} failures.")

    # 3) Partial save
    partial_path = os.path.join(output_dir, "raw_speeches_partial.json")
    with open(partial_path, "w", encoding="utf-8") as f:
        json.dump(speeches, f, ensure_ascii=False, indent=2)
    print(f"[✓] Partial speeches saved to {partial_path}")

    # 4) Save full set
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(speeches, f, ensure_ascii=False, indent=2)
    print(f"[✓] Full raw_speeches.json updated ({len(speeches)} speeches).")

    # 5) Keyword analysis
    summary_df, top_speeches = keyword_analysis(
        speeches, keywords, start_date=start_date, end_date=end_date, top_n=10
    )
    print("\n=== Keyword Frequencies Summary Table ===")
    display(summary_df)

    print("\n=== Top Speeches by Total Mentions ===")
    for title, cnt in top_speeches:
        print(f"{cnt} mentions — {title}")

    # 6) Topic modeling
    tm_results = run_topic_modeling(
        speeches, num_topics=num_topics, passes=passes, compute_coherence=True
    )

    # 7) Trend visualization
    visualize_term_trends(speeches, keywords, window=1)

    # 8) Export keyword summary
    csv_path   = os.path.join(output_dir, "keyword_summary.csv")
    excel_path = os.path.join(output_dir, "keyword_summary.xlsx")
    summary_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary_df.to_excel(excel_path, index=False)
    print(f"[✓] Keyword table saved to:\n  • {csv_path}\n  • {excel_path}")

    return {
        "speeches": speeches,
        "failures": failures,
        "summary_df": summary_df,
        "top_speeches": top_speeches,
        "topic_model": tm_results,
    }

# 🟩 CELL 9: Run
main()

