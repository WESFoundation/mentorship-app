with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

import re
for m in re.finditer(r'@app\.route\("/certificate"', content):
    start = m.start()
    func_start = content.find('def ', start)
    if func_start >= 0:
        func_end = content.find(':', func_start)
        if func_end >= 0:
            print(content[func_start:func_end+1])
            break