#!/usr/bin/env python3
import re
import sys
from pathlib import Path

PATTERN = re.compile(
    r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9_.-]+\))?!?: .{1,72}$'
)


def main() -> int:
    if len(sys.argv) != 2:
        print('Usage: validate_commit_msg.py <commit-msg-file>')
        return 1

    msg_path = Path(sys.argv[1])
    if not msg_path.exists():
        print(f'Commit message file not found: {msg_path}')
        return 1

    first_line = msg_path.read_text(encoding='utf-8').splitlines()[0].strip()
    if PATTERN.match(first_line):
        return 0

    print('Invalid commit message format.')
    print('Expected: <type>(optional-scope): <subject>')
    print('Allowed types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert')
    print('Examples:')
    print('  feat(knowledge): add rag search endpoint')
    print('  fix(worker): handle empty queue timeout')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
