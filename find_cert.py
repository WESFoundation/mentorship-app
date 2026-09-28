with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

import re
for m in re.finditer(r'certificate', content):
    start = max(0, m.start() - 50)
    end = min(len(content), m.end() + 50)
    print(content[start:end])
    print('---')