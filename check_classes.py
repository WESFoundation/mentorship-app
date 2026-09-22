with open('templates/supervisor/institution.html', 'r') as f:
    content = f.read()
print('address-cell:', 'address-cell' in content)
print('class="address-cell"', 'class="address-cell"' in content)
print('address-full hidden:', 'address-full hidden' in content)
print('description-full hidden:', 'description-full hidden' in content)