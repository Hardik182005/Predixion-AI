"""Source normalization, classification, filtering, de-duplication, and passage selection.

Everything here is deterministic application code. Webpage text is untrusted
data: it is cleaned, screened for instruction-like content, chunked, and only
bounded passages are shown to the model.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from urllib.parse import urlsplit

from .contracts import Passage, SourceKind, SourceTier
from .urls import hostname

MAX_CONTENT_CHARS = 60_000
MIN_USEFUL_CHARS = 200
PASSAGE_TARGET_CHARS = 700
PASSAGE_MAX_CHARS = 1_100

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "them",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "vs",
        "versus",
        "compare",
        "comparison",
        "find",
        "top",
        "best",
        "summarize",
        "summary",
        "research",
        "pros",
        "cons",
        "about",
        "between",
        "using",
        "use",
        "different",
        "approaches",
        "approach",
        "startup",
        "startups",
        "adding",
        "add",
        "five",
        "three",
        "two",
        "one",
        "3",
        "5",
        "do",
        "does",
        "should",
        "can",
        "could",
        "would",
        "i",
        "we",
        "you",
        "our",
        "your",
        "my",
        "me",
    ]
)

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))*\)")
_RAW_URL = re.compile(r"https?://\S+")
_HTML_TAG = re.compile(r"<[^>]{1,200}>")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|`+|~~)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_SPACES = re.compile(r"[ \t\f\v]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")

# Defense in depth only. Structural controls (fixed tools, ID-only reads,
# validated follow-ups, quote checks, verification) are the primary controls.
INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts|messages)",
        r"disregard (all |any )?(the )?(previous|prior|above|system) (instructions|prompt)",
        r"\b(system|developer) prompt\b",
        r"\byou are now\b",
        r"\bact as (an?|the) (ai|assistant|system)\b",
        r"\b(new|updated) instructions?:",
        r"\bdo not (tell|inform|mention to) the user\b",
        r"\b(reveal|print|send|exfiltrate|leak) (your|the) (api key|secret|credentials|system prompt)",
        r"\bcall the \w+ tool\b",
        r"<\s*/?\s*(system|assistant|instructions?)\s*>",
        r"\bassistant\s*:\s",
    )
]

PAYWALL_MARKERS = (
    "subscribe to continue reading",
    "to continue reading, subscribe",
    "this article is for subscribers",
    "sign in to continue reading",
    "create a free account to continue",
    "you have reached your free article limit",
    "please enable javascript",
    "access denied",
    "verify you are human",
)

NON_TEXT_EXTENSIONS = (
    ".zip",
    ".gz",
    ".tar",
    ".exe",
    ".dmg",
    ".msi",
    ".apk",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
    ".json",
    ".xml",
)

_CODE_HOSTS = ("github.com", "gitlab.com", "pypi.org", "npmjs.com", "huggingface.co", "bitbucket.org")
_ACADEMIC_HOSTS = (
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "springer.com",
    "sciencedirect.com",
    "nature.com",
    "aclanthology.org",
    "openreview.net",
    "semanticscholar.org",
    "researchgate.net",
    "nih.gov",
)
_COMMUNITY_HOSTS = (
    "reddit.com",
    "quora.com",
    "stackoverflow.com",
    "stackexchange.com",
    "news.ycombinator.com",
    "dev.to",
    "hashnode.dev",
    "discord.com",
    "x.com",
    "twitter.com",
    "facebook.com",
)
_AGGREGATOR_HOSTS = (
    "g2.com",
    "capterra.com",
    "getapp.com",
    "crunchbase.com",
    "tracxn.com",
    "softwaresuggest.com",
    "clutch.co",
    "saasworthy.com",
    "producthunt.com",
    "wellfound.com",
    "linkedin.com",
    "zoominfo.com",
    "owler.com",
    "cbinsights.com",
    "pitchbook.com",
    "f6s.com",
    "glassdoor.com",
    "ambitionbox.com",
    "slideshare.net",
    "scribd.com",
)
_NEWS_HOSTS = (
    "techcrunch.com",
    "reuters.com",
    "bloomberg.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "inc42.com",
    "yourstory.com",
    "entrackr.com",
    "theverge.com",
    "venturebeat.com",
    "forbes.com",
    "thehindubusinessline.com",
    "moneycontrol.com",
    "business-standard.com",
    "theregister.com",
    "infoq.com",
    "zdnet.com",
    "wired.com",
    "the-ken.com",
    "medianama.com",
    "businesswire.com",
    "prnewswire.com",
)
_LISTICLE = re.compile(r"\b(top|best)\s+\d{1,2}\b|\b\d{1,2}\s+(best|top)\b", re.IGNORECASE)


def _host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in suffixes)


def classify_source(url: str, title: str = "") -> tuple[SourceKind, SourceTier]:
    """Heuristic source type and suitability tier. Documented in docs/security.md and README."""
    host = hostname(url)
    path = urlsplit(url).path.lower()
    if (
        host.endswith((".gov", ".gov.in", ".gov.uk", ".europa.eu"))
        or _host_matches(host, _ACADEMIC_HOSTS)
        or host.endswith((".edu", ".ac.in", ".ac.uk"))
    ):
        return SourceKind.academic, SourceTier.high
    if _host_matches(host, _CODE_HOSTS):
        return SourceKind.code_repository, SourceTier.high
    if host.startswith(("docs.", "developer.", "developers.", "learn.")) or "/docs" in path or "/documentation" in path:
        return SourceKind.official_docs, SourceTier.high
    if _host_matches(host, _COMMUNITY_HOSTS):
        return SourceKind.community, SourceTier.low
    if _host_matches(host, _AGGREGATOR_HOSTS):
        return SourceKind.aggregator, SourceTier.low
    if _host_matches(host, _NEWS_HOSTS):
        return SourceKind.news, SourceTier.medium
    if _LISTICLE.search(title):
        return SourceKind.aggregator, SourceTier.low
    if "/blog" in path or host.startswith("blog.") or "medium.com" in host or "substack.com" in host:
        return SourceKind.blog, SourceTier.medium
    return SourceKind.company_site, SourceTier.medium


# ---------------------------------------------------------------------------
# Text normalization


_QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
        "​": "",
        "…": "...",
    }
)


def normalize_for_match(text: str) -> str:
    """Conservative normalization used for quotation matching.

    NFKC, typographic quotes/dashes to ASCII, markdown emphasis removed,
    whitespace collapsed, case-folded. Words, digits, and punctuation that
    carry meaning are preserved, so a paraphrase does not match.
    """
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_MAP)
    text = _MD_EMPHASIS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def clean_content(raw: str) -> str:
    """Convert provider markdown/text into plain paragraphs for passage selection."""
    text = unicodedata.normalize("NFKC", raw or "").translate(_QUOTE_MAP)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    text = _RAW_URL.sub("", text)
    text = _HEADING.sub("", text)
    text = _MD_EMPHASIS.sub("", text)
    lines = []
    for line in text.splitlines():
        line = _SPACES.sub(" ", line).strip(" |-")
        if line and not re.fullmatch(r"[\W_]+", line):
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:MAX_CONTENT_CHARS]


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_match(text).encode("utf-8")).hexdigest()


def shingles(text: str, k: int = 5, limit_words: int = 3_000) -> set[int]:
    words = tokenize(text, keep_stopwords=True)[:limit_words]
    if len(words) < k:
        return {hash(" ".join(words))} if words else set()
    return {hash(" ".join(words[i : i + k])) for i in range(len(words) - k + 1)}


def jaccard(a: set[int], b: set[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    words = _WORD.findall(text.casefold())
    if keep_stopwords:
        return words
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def screen_injection(text: str) -> tuple[str, list[str]]:
    """Remove sentences that look like instructions to an AI system.

    Returns the screened text and the removed sentences. This is a heuristic
    with false positives and negatives; it is not the primary defense.
    """
    removed: list[str] = []
    kept_paragraphs = []
    for paragraph in text.split("\n"):
        sentences = _SENTENCE_SPLIT.split(paragraph)
        kept = []
        for sentence in sentences:
            if any(p.search(sentence) for p in INJECTION_PATTERNS):
                removed.append(sentence.strip()[:300])
            else:
                kept.append(sentence)
        kept_paragraphs.append(" ".join(kept))
    return "\n".join(kept_paragraphs), removed


def looks_paywalled(text: str) -> bool:
    lower = text[:4_000].casefold()
    return any(marker in lower for marker in PAYWALL_MARKERS) and len(text) < 3_000


def has_non_text_extension(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(NON_TEXT_EXTENSIONS)


# ---------------------------------------------------------------------------
# Dates


_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_DATE_CONTEXT = re.compile(
    r"(published|posted|updated|last updated|last modified|released|date)\s*(on|:)?\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9}\.? \d{4})",
    re.IGNORECASE,
)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})", value)
    if m and m.group(1).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2}) ([A-Za-z]{3,9})\.? (\d{4})", value)
    if m and m.group(2).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            return None
    return None


def find_page_date(text: str) -> date | None:
    """Find an explicitly labeled publication/update date near the top of a page."""
    for match in _DATE_CONTEXT.finditer(text[:3_000]):
        parsed = parse_date(match.group("date"))
        if parsed and 1990 <= parsed.year <= date.today().year + 1:
            return parsed
    return None


# ---------------------------------------------------------------------------
# Passages


_CONNECTIVE = re.compile(r"^(however|but|although|that said|in contrast|on the other hand|note|caveat|except)\b", re.I)


def chunk_passages(source_id: str, text: str) -> list[Passage]:
    """Paragraph-aware chunks so qualifications in the same paragraph stay together."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_start = 0
    cursor = 0
    offsets: list[int] = []
    for p in paragraphs:
        idx = text.find(p, cursor)
        offsets.append(idx if idx >= 0 else cursor)
        cursor = (idx if idx >= 0 else cursor) + len(p)

    def flush() -> None:
        if buf:
            chunks.append((buf_start, "\n".join(buf)))

    for p, start in zip(paragraphs, offsets, strict=True):
        if len(p) > PASSAGE_MAX_CHARS:
            flush()
            buf = []
            piece, piece_start = "", start
            for sentence in _SENTENCE_SPLIT.split(p):
                if piece and len(piece) + len(sentence) + 1 > PASSAGE_TARGET_CHARS:
                    chunks.append((piece_start, piece))
                    piece_start += len(piece) + 1
                    piece = sentence
                else:
                    piece = f"{piece} {sentence}".strip()
            if piece:
                chunks.append((piece_start, piece))
            continue
        if not buf:
            buf, buf_start = [p], start
        elif sum(len(b) for b in buf) + len(p) <= PASSAGE_TARGET_CHARS:
            buf.append(p)
        else:
            flush()
            buf, buf_start = [p], start
    flush()
    return [
        Passage(id=f"{source_id}.P{i}", text=chunk[:PASSAGE_MAX_CHARS], start=start)
        for i, (start, chunk) in enumerate(chunks, start=1)
    ]


def score_passages(passages: list[Passage], terms: list[str]) -> list[float]:
    """BM25-style lexical relevance of each passage to the research terms."""
    query = [t for t in dict.fromkeys(tokenize(" ".join(terms)))]
    if not query or not passages:
        return [0.0] * len(passages)
    docs = [Counter(tokenize(p.text)) for p in passages]
    n = len(docs)
    avg_len = sum(sum(d.values()) for d in docs) / n or 1.0
    df = {t: sum(1 for d in docs if t in d) for t in query}
    k1, b = 1.2, 0.75
    scores = []
    for d in docs:
        length = sum(d.values()) or 1
        s = 0.0
        for t in query:
            tf = d.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        scores.append(s)
    return scores


def select_passages(passages: list[Passage], terms: list[str], k: int) -> list[Passage]:
    """Top-k relevant passages in document order, pulling in the preceding passage
    when a selected one starts with a qualifying connective ("However, ...")."""
    if not passages:
        return []
    scores = score_passages(passages, terms)
    ranked = sorted(range(len(passages)), key=lambda i: scores[i], reverse=True)
    chosen = {i for i in ranked[:k] if scores[i] > 0}
    if not chosen:
        chosen = {0}
    for i in sorted(chosen):
        if i > 0 and _CONNECTIVE.match(passages[i].text) and len(chosen) < k + 2:
            chosen.add(i - 1)
    return [passages[i] for i in sorted(chosen)]


def term_overlap(text: str, terms: list[str]) -> float:
    wanted = set(tokenize(" ".join(terms)))
    if not wanted:
        return 0.0
    have = set(tokenize(text))
    return len(wanted & have) / len(wanted)


def entity_token(entity: str) -> str:
    return re.sub(r"[^a-z0-9]", "", entity.casefold())


def is_first_party(url: str, entity: str | None) -> bool:
    """A source is first-party for an entity when the entity's name appears in its hostname."""
    if not entity:
        return False
    token = entity_token(entity)
    if len(token) < 3:
        return False
    host = re.sub(r"[^a-z0-9]", "", hostname(url))
    first_word = entity_token(entity.split()[0]) if entity.split() else ""
    return token in host or (len(first_word) >= 5 and first_word in host)
