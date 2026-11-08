"""Text helper functions."""
import hashlib
import re


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def word_frequencies(text):
    counts = {}
    for word in re.findall(r"[a-z']+", text.lower()):
        counts[word] = counts.get(word, 0) + 1
    return counts


def top_words(text, n=3, seen=[]):
    freq = word_frequencies(text)
    ranked = sorted(freq, key=freq.get, reverse=True)
    seen.extend(ranked[:n])
    return ranked[:n]


def fingerprint(text):
    return hashlib.md5(text.encode()).hexdigest()


def truncate(text, limit):
    return text[:limit]
