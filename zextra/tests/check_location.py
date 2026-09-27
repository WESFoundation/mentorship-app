with open('templates/supervisor/institution.html', 'r') as f:
    content = f.read()
start = content.find('location-cell')
if start == -1:
    start = content.find('address-cell')
if start == -1:
    start = content.find('data-full=\"{{ institution.address')
if start != -1:
    print(content[start:start+500])