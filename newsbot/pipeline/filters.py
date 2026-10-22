"""
Фильтр по ключевым словам и исключениям с учётом словоформ.

Правила совпадения слова из статьи со словом из ключевой фразы:
- по лемме: «Китай» находит «Китая», «Китаю»; «газ» находит «газа», но не «газета»;
- по началу слова, если слово ключа не короче PREFIX_MIN_LEN букв:
  «Китай» находит «китайский», «металл» — «металлургия» (как прежний поиск подстроки);
- по началу слова, если ключ оканчивается на «*»: «нефт*» находит «нефтяной», «газ*» — «Газпром».
Фраза из нескольких слов («Параллельный импорт») ищется как подряд идущие слова.
"""
import re
from functools import lru_cache

import pymorphy3

PREFIX_MIN_LEN = 5
WORD_RE = re.compile(r'\w+')

_morph = None


def _analyzer():
    global _morph
    if _morph is None:
        _morph = pymorphy3.MorphAnalyzer()
    return _morph

def _norm(word: str) -> str:
    return word.lower().replace('ё', 'е')

@lru_cache(maxsize=100_000)
def lemma(word: str) -> str:
    return _norm(_analyzer().parse(word)[0].normal_form)

def tokenize(text: str) -> list[tuple[str, str]]:
    """Список пар (слово, лемма) в нижнем регистре."""
    return [(w, lemma(w)) for w in (_norm(m) for m in WORD_RE.findall(text))]


class Keyword:
    def __init__(self, phrase: str):
        self.phrase = phrase.strip()
        explicit_prefix = self.phrase.endswith('*')
        words = [_norm(w) for w in WORD_RE.findall(self.phrase.rstrip('*'))]
        # Каждое слово ключа: (лемма, префикс или None)
        self.parts = []
        for i, word in enumerate(words):
            word_lemma = lemma(word)
            if explicit_prefix and i == len(words) - 1:
                prefix = word
            elif len(word_lemma) >= PREFIX_MIN_LEN:
                prefix = word_lemma
            else:
                prefix = None
            self.parts.append((word_lemma, prefix))

    @staticmethod
    def _part_matches(token, part) -> bool:
        word, word_lemma = token
        part_lemma, prefix = part
        if word_lemma == part_lemma:
            return True
        return prefix is not None and (word.startswith(prefix) or word_lemma.startswith(prefix))

    def found_in(self, tokens: list[tuple[str, str]]) -> bool:
        n = len(self.parts)
        if n == 0:
            return False
        return any(
            all(self._part_matches(tokens[i + j], self.parts[j]) for j in range(n))
            for i in range(len(tokens) - n + 1)
        )

    def __repr__(self):
        return f"Keyword({self.phrase!r})"


class ArticleFilter:
    def __init__(self, keywords: list[str], excluded: list[str]):
        self.keywords = [Keyword(k) for k in keywords if k.strip()]
        self.excluded = [Keyword(k) for k in excluded if k.strip()]

    def check(self, text: str) -> tuple[bool, str | None]:
        """(принята ли статья, сработавшее слово — ключ или исключение)."""
        tokens = tokenize(text)
        matched = next((k for k in self.keywords if k.found_in(tokens)), None)
        if matched is None:
            return False, None
        blocked = next((k for k in self.excluded if k.found_in(tokens)), None)
        if blocked is not None:
            return False, blocked.phrase
        return True, matched.phrase

    def accepts(self, text: str) -> bool:
        return self.check(text)[0]
