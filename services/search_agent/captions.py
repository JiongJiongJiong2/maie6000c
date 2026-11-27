"""Use legible caption phrases for source discovery and image-level evidence."""

import re
from urllib.parse import unquote


def words(text):
    return re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)


def generic_subject(name):
    tokens = words(name)
    return bool(tokens) and all(
        t
        in {
            "a",
            "an",
            "the",
            "young",
            "adult",
            "person",
            "people",
            "man",
            "woman",
            "boy",
            "girl",
            "child",
            "male",
            "female",
            "human",
            "animal",
            "cat",
            "dog",
            "character",
            "人物",
            "男人",
            "女人",
            "女性",
            "男性",
            "女孩",
            "男孩",
            "小孩",
            "猫",
            "狗",
        }
        for t in tokens
    )


def caption_phrases(text):
    phrases = []
    for line in re.split(r"[\n:：!?！？]+", text):
        tokens = words(line)
        if len(tokens) < 3 and not re.search(r"[\u3400-\u9fff]{4,}", line):
            continue
        phrase = " ".join(tokens[:12])[:96].strip()
        if (len(phrase) >= 10 or re.search(r"[㐀-鿿]{4,}", phrase)) and phrase not in phrases:
            phrases.append(phrase)
    return phrases[:3]


def caption_overlap(phrases, label):
    """Proportion of a caption's adjacent word pairs found in a single clue."""
    text = " ".join(words(label))
    best = 0.0
    for phrase in phrases:
        tokens = phrase.split()
        if f" {phrase} " in f" {text} ":
            return 1.0
        pairs = set(zip(tokens, tokens[1:]))
        if len(pairs) >= 2:
            other = text.split()
            hits = len(pairs.intersection(zip(other, other[1:])))
            if hits >= 2:
                best = max(best, hits / len(pairs))
    return best


def image_label(url, alt):
    filename = unquote(url.split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    return (alt + " " + filename.replace("-", " ").replace("_", " ")).strip()[:500]


def product_listing(url, title=""):
    """Recognize product-detail URLs and merchandise mockups in search results."""
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    path = unquote(parsed.path).casefold()
    host = (parsed.hostname or "").lower()
    if re.search(r"(?:^|\.)amazon\.[a-z.]+$", host) and re.search(r"/(?:dp|gp/product)/", path):
        return True
    if re.search(r"/(?:products?|listings?|phone-cases?|t-shirts?|stickers?|mugs?)/", path):
        return True
    merchandising = re.compile(
        r"\b(?:phone case|t[ -]shirt|hoodie|throw pillow|tote bag|cut file|svg cut|"
        r"vinyl decal|sentiment design)\b",
        re.I,
    )
    return bool(merchandising.search(title) or host.endswith(".silhouettedesignstore.com"))


def wants_products(text):
    return bool(
        re.search(
            r"\b(?:merch(?:andise)?|buy|shop|product|t[ -]shirt|phone case)\b|周边|购买", text, re.I
        )
    )
