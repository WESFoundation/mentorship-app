from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201
    
    response = client.get('/institution')
    content = response.data.decode('utf-8')
    
    print('Institution page:', response.status_code)
    checks = [
        ('3 dots', 'fa-ellipsis-v' in content),
        ('toggleDropdown', 'toggleDropdown' in content),
        ('toggleDescription', 'toggleDescription' in content),
        ('toggleLocation', 'toggleLocation' in content),
        ('dropdown fixed', "dropdown.style.position = 'fixed'" in content),
        ('See less', 'See less' in content),
    ]
    for name, result in checks:
        print(name + ': ' + ('PASS' if result else 'FAIL'))