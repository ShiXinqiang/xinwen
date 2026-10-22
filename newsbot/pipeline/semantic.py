"""Семантический отбор по близости к эталонным векторам тем."""
from newsbot import storage
from newsbot.pipeline.normalize import normalize_text


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    norm_a = sum(x*x for x in a)**0.5
    norm_b = sum(y*y for y in b)**0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

def semantic_filter(articles, topic_embeddings: dict, threshold: float, embed, limit: int = 30):
    """
    Оставляет статьи, близкие хотя бы к одной теме. embed(text) -> вектор или None.
    Возвращает (статьи, {'passed', 'failed', 'avg_similarity'}).
    """
    passed, failed, similarities = [], 0, []
    for a in articles[:limit]:
        text = normalize_text(a['title'] + ' ' + a['description'])[:500]
        emb = storage.get_embedding(a['_hash'])
        if emb is None:
            emb = embed(text)
            if not emb:
                failed += 1
                continue
            storage.save_embedding(a['_hash'], emb)
        max_sim = max(cosine_similarity(emb, vec) for vec in topic_embeddings.values())
        similarities.append(max_sim)
        if max_sim >= threshold:
            passed.append(a)
        else:
            failed += 1
    avg = sum(similarities) / len(similarities) if similarities else 0.0
    return passed, {'passed': len(passed), 'failed': failed, 'avg_similarity': avg}
