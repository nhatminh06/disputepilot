import os
import re
from pathlib import Path


POLICY_DIR = Path(__file__).resolve().parent.parent / 'policies'
POLICY_IDS = ('shipping', 'refunds', 'returns')
QUERIES = {
    'MERCHANDISE_OR_SERVICE_NOT_RECEIVED': 'shipping tracking delivery missing',
    'MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED': 'returns condition refund',
    'UNAUTHORISED': 'refund eligibility',
}


def search_policy(query: str, limit: int = 3) -> list[dict[str, str]]:
    if len(query) > 500 or not 1 <= limit <= 3:
        raise ValueError('Query must be at most 500 characters; limit must be 1 to 3.')
    terms = set(re.findall(r'[a-z0-9]+', query.lower()))
    matches = []
    # Only fixed filenames are opened, without following directory or file symlinks.
    try:
        directory = os.open(POLICY_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    try:
        for policy_id in POLICY_IDS:
            try:
                fd = os.open(f'{policy_id}.md', os.O_RDONLY | os.O_NOFOLLOW,
                             dir_fd=directory)
            except FileNotFoundError:
                continue
            with os.fdopen(fd, 'r', encoding='utf-8', newline='') as file:
                text = file.read(16385)
            if len(text) > 16384:
                continue
            sections = list(re.finditer(r'^## ([^\r\n]+)', text, re.MULTILINE))
            seen = set()
            for index, section in enumerate(sections):
                section_id = re.sub(r'[^a-z0-9]+', '-', section[1].lower()).strip('-')
                if not section_id or section_id in seen:
                    continue
                seen.add(section_id)
                end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
                excerpt = text[section.start():end][:1200]
                score = len(terms & set(re.findall(r'[a-z0-9]+', excerpt.lower())))
                if score:
                    matches.append((score, {
                        'policy_id': policy_id, 'section_id': section_id,
                        'excerpt': excerpt, 'source_path': f'policies/{policy_id}.md',
                    }))
    finally:
        os.close(directory)
    matches.sort(key=lambda item: (-item[0], item[1]['policy_id'], item[1]['section_id']))
    return [item for _, item in matches[:limit]]
