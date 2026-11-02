import regex
from fastapi import HTTPException


def compiled(rule):
    pattern = rule['pattern']
    if rule['rule_type'] == 'KEYWORD':
        pattern = regex.escape(pattern)
        if rule['match_mode'] == 'WORD':
            pattern = r'(?<![\p{L}\p{N}_])' + pattern + r'(?![\p{L}\p{N}_])'
    return regex.compile(pattern, 0 if rule['case_sensitive'] else regex.IGNORECASE)


def validate(rule):
    try:
        rx = compiled(rule)
        for sample in ['', 'a' * 20000 + '!', '가' * 20000 + '!']:
            list(rx.finditer(sample, timeout=0.02))
        if rx.match('', timeout=0.02):
            raise ValueError('empty match')
    except (regex.error, TimeoutError, ValueError):
        raise HTTPException(400, '정규식이 잘못되었거나 실행 비용이 높습니다.')


def mask(text, rules):
    spans = []
    try:
        for rank, rule in enumerate(rules):
            for match in compiled(rule).finditer(text, timeout=0.02):
                if match.end() > match.start():
                    spans.append((match.start(), match.end(), rank, rule['replacement']))
    except (TimeoutError, regex.error):
        # Fail closed: never expose an original string when filtering fails.
        return '[표현 필터 처리 제한으로 내용을 표시할 수 없습니다.]'
    spans.sort()
    merged = []
    for start, end, rank, replacement in spans:
        if merged and start < merged[-1][1]:
            old = merged[-1]
            merged[-1] = (old[0], max(end, old[1]), min(rank, old[2]),
                          replacement if rank < old[2] else old[3])
        else:
            merged.append((start, end, rank, replacement))
    result, cursor = [], 0
    for start, end, _, replacement in merged:
        result.extend([text[cursor:start], replacement])
        cursor = end
    return ''.join(result) + text[cursor:]
