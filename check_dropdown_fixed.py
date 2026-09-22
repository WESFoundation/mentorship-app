with open('templates/supervisor/institution.html', 'r') as f:
    content = f.read()
print('position: fixed' in content)
print("dropdown.style.position = 'fixed'" in content)