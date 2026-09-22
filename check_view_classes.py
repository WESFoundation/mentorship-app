with open('templates/supervisor/view_institution.html', 'r') as f:
    content = f.read()
print('address-cell:', 'address-cell' in content)
print('location-cell:', 'location-cell' in content)
print('address-full:', 'address-full' in content)
print('address-full hidden:', 'address-full hidden' in content)
print('description-full:', 'description-full' in content)
print('description-full hidden:', 'description-full hidden' in content)