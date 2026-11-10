"""Lexical polarity evidence for review triage, without statistical confidence."""
import re


_WEIGHTS = {
    **dict.fromkeys(('excellent', 'amazing', 'fantastic', 'wonderful', 'perfect',
                     'outstanding', 'beautiful', 'love', 'loved', 'delicious',
                     'impressive', 'breathtaking', 'superb', 'sedap', 'cantik',
                     'terbaik', 'seronok'), 2),
    **dict.fromkeys(('enjoy', 'enjoyed', 'enjoyable', 'pleasant', 'lovely',
                     'interesting', 'good', 'great', 'nice', 'worthwhile',
                     'relaxing', 'memorable', 'friendly', 'clean', 'satisfying',
                     'peaceful', 'helpful', 'bagus', 'menarik', 'puas'), 1),
    **dict.fromkeys(('terrible', 'awful', 'worst', 'horrible', 'disappointing',
                     'disappointed', 'frustrating', 'frustrated', 'uncomfortable',
                     'poor', 'bad', 'dirty', 'rude', 'overpriced', 'boring',
                     'unpleasant', 'underwhelming', 'waste', 'teruk', 'buruk',
                     'kecewa', 'kotor'), -2),
    **dict.fromkeys(('crowded', 'crowds', 'noisy', 'tiring', 'difficult',
                     'confusing', 'sesak', 'lambat'), -1),
    'highly recommend': 2, 'highly recommended': 2, 'worth visiting': 2,
    'worth the visit': 2, 'would visit again': 2, 'would come again': 2,
    'exceeded my expectations': 2, 'cannot recommend it enough': 2,
    'long queues': -2, 'long waiting time': -2, 'too crowded': -2, 'slow service': -1,
    'would not return': -2, 'would not recommend': -2,
    'did not meet my expectations': -2, 'not worth': -2,
    'tak berbaloi': -2, 'tidak berbaloi': -2,
}
_BALANCED = {'okay', 'ok', 'average', 'decent', 'ordinary', 'so-so', 'biasa'}
_NEGATIONS = {'not', 'no', 'never', 'hardly', 'without', 'tak', 'tidak', 'bukan', 'kurang'}
_CLAUSE_BOUNDARIES = re.compile(r"[.!?;,。！？；，\n]|\b(?:and|or|but|yet|however|although|tetapi|walaupun)\b")
_SIGNALS = re.compile(
    r"\b(?:" + '|'.join(re.escape(word) for word in
                         sorted(_WEIGHTS.keys() | _BALANCED, key=lambda word: (-len(word), word))) + r")\b"
)


def classify_review_sentiment(normalized, rating):
    """Score distinct expressions, leaving mixed and unclear reviews to the Administrator."""
    normalized = normalized.replace('’', "'")
    normalized = re.sub(r"\bcan't\b", "can not", normalized)
    normalized = re.sub(r"\bwon't\b", "will not", normalized)
    normalized = re.sub(r"\b(\w+)n't\b", r'\1 not', normalized)
    normalized = re.sub(r'\bnot\s+(?:only|just)\b', '', normalized)
    normalized = re.sub(r'[^\S\n]+', ' ', normalized)
    positive, negative = {}, {}
    balanced = False
    for clause in _CLAUSE_BOUNDARIES.split(normalized):
        preceding_end = 0
        for match in _SIGNALS.finditer(clause):
            phrase = match[0]
            context = re.findall(r'\w+', clause[preceding_end:match.start()])[-4:]
            preceding_end = match.end()
            negated = bool(_NEGATIONS.intersection(context))
            if phrase in _BALANCED:
                balanced |= not negated
                continue
            weight = _WEIGHTS[phrase]
            if negated:
                # "Not terrible" is mild approval at most.
                weight = 1 if weight < 0 else -weight
            evidence = positive if weight > 0 else negative
            evidence[phrase] = max(evidence.get(phrase, 0), abs(weight))

    if positive and negative:
        label = 'mixed'
    elif balanced:
        label = 'mixed' if positive or negative else 'neutral'
    elif positive or negative:
        label = 'positive' if positive else 'negative'
    else:
        label = 'uncertain'

    valid_rating = type(rating) is int and 1 <= rating <= 5
    disagreement = valid_rating and (
        (rating in (4, 5) and label == 'negative') or
        (rating in (1, 2) and label == 'positive')
    )
    opposite = negative if label == 'negative' else positive
    mismatch = disagreement and len(opposite) >= 2 and sum(opposite.values()) >= 3
    return {
        'method': 'lexical_negation_v1',
        'label': label,
        'positiveEvidence': len(positive),
        'negativeEvidence': len(negative),
        'ratingMismatch': mismatch,
        'ratingAlignment': ('mismatch' if mismatch else 'uncertain'
                            if disagreement or not valid_rating or label == 'uncertain' else 'compatible'),
    }
