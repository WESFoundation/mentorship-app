with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

idx = content.find('def my_certificate')
if idx >= 0:
    rest = content[idx:]
    next_def = rest.find('\ndef ', 1)
    next_route = rest.find('\n@app.route', 1)
    if next_def >= 0 and (next_route < 0 or next_def < next_route):
        end_idx = next_def
    else:
        end_idx = next_route
    if end_idx > 0:
        with open('my_certificate.txt', 'w', encoding='utf-8') as f:
            f.write(content[idx:idx+end_idx])
        print('Done')
    else:
        print('Could not find end')
else:
    print('Function not found')