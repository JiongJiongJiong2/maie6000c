"""Deterministic, metadata-only matching for one private library."""

import re
import unicodedata

from services.common.library_metadata import effective_labels

CONCEPTS = {
    "subject_tags": {
        "猫": ("猫", "cat", "kitten"),
        "狗": ("狗", "dog", "puppy"),
        "人物": ("人物", "人类", "person", "human"),
        "卡通": ("卡通", "动漫", "cartoon"),
    },
    "action_tags": {
        "鼓掌": ("鼓掌", "拍手", "applaud", "clap", "clapping"),
        "摇头": ("摇头", "shake head", "shaking head"),
        "点头": ("点头", "nod", "nodding"),
        "翻白眼": ("翻白眼", "roll eyes", "eye roll"),
        "挥手": ("挥手", "招手", "wave", "waving"),
        "大笑": ("大笑", "爆笑", "笑死", "laugh", "laughing"),
        "哭": ("哭", "流泪", "cry", "crying"),
    },
    "emotion_tags": {
        "无奈": ("无奈", "无语", "helpless", "resigned"),
        "开心": ("开心", "高兴", "快乐", "happy", "joy"),
        "生气": ("生气", "愤怒", "angry", "furious"),
        "惊讶": ("惊讶", "震惊", "surprise", "surprised", "shocked"),
        "尴尬": ("尴尬", "awkward", "embarrassed"),
        "难过": ("难过", "悲伤", "sad", "upset"),
        "困惑": ("困惑", "迷惑", "疑惑", "confused"),
    },
    "tone_tags": {
        "讽刺": ("讽刺", "阴阳怪气", "嘲讽", "sarcastic", "sarcasm", "ironic"),
        "敷衍": ("敷衍", "perfunctory"),
    },
}
QUOTED = re.compile(r'「([^」]+)」|『([^』]+)』|“([^”]+)”|"([^"]+)"')
FILLER = re.compile(r"找一下|找一个|有没有|那个|表情包|表情|动图|写着|给我|想找|[的了呢吗]")
STOP_WORDS = {"a", "an", "the", "gif", "meme", "find", "with", "that", "for", "show", "me"}


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def contains(text: str, term: str) -> bool:
    if term.isascii():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def prepare_query(query: str):
    query = normalize(query)
    quoted = [next(value for value in match.groups() if value) for match in QUOTED.finditer(query)]
    unquoted = QUOTED.sub(" ", query)
    concepts = {
        category: {
            name for name, aliases in words.items() if any(contains(unquoted, x) for x in aliases)
        }
        for category, words in CONCEPTS.items()
    }
    terms = set(re.findall(r"[a-z0-9]+", unquoted)) - STOP_WORDS
    for run in re.findall(r"[\u3400-\u9fff]+", FILLER.sub(" ", unquoted)):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return query, quoted, concepts, terms


def rank(prepared, title: str, manual: dict, annotation: dict):
    query, quoted, concepts, terms = prepared
    tags = [normalize(tag) for tag in manual.get("tags", [])]
    title = normalize(title)
    ocr = normalize(manual.get("ocr_text", annotation.get("ocr_text", "")))
    labels = effective_labels(manual, annotation)
    captions = normalize(
        " ".join(annotation.get(key) or "" for key in ("caption_zh", "caption_en"))
    )
    reasons = []
    exact = [term for term in quoted if contains(ocr, term) or any(contains(t, term) for t in tags)]
    reasons.extend(f"文字「{term}」" for term in exact)
    groups = 0
    for category, names in concepts.items():
        matches = [
            name
            for name in sorted(names)
            if any(
                contains(field, alias)
                for alias in CONCEPTS[category][name]
                for field in [*tags, *(normalize(t) for t in labels[category])]
            )
        ]
        if matches:
            groups += 1
            reasons.extend(matches)
    fields = [(title, 8, "标题"), (ocr, 7, "文字"), (captions, 2, "描述")]
    fields.extend((tag, 9, "手动标签") for tag in tags)
    fields.extend((normalize(tag), 4, "标签") for tags_ in labels.values() for tag in tags_)
    direct = max((weight for value, weight, _ in fields if contains(value, query)), default=0)
    hits = {}
    for value, weight, field in fields:
        matched = [term for term in sorted(terms) if contains(value, term)]
        if matched:
            hits[field] = max(hits.get(field, 0), weight * len(matched))
    reasons.extend(hits)
    if direct:
        reasons.extend(
            field for value, weight, field in fields if weight == direct and contains(value, query)
        )
    return (len(exact), groups, direct, sum(hits.values())), list(dict.fromkeys(reasons))
