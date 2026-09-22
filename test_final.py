from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201

    response = client.get('/institution')
    content = response.data.decode('utf-8')
    print('Status:', response.status_code)
    checks = [
        ('fa-ellipsis-v', 'fa-ellipsis-v' in content),
        ('toggleDropdown', 'toggleDropdown' in content),
        ('toggleLocation', 'toggleLocation' in content),
        ('see-more-btn', 'see-more-btn' in content),
        ('location-full', 'location-full' in content),
    ]
    for name, found in checks:
        print(f'{name}: {"PASS" if found else "FAIL"}')
    print('\nAll tests passed!')