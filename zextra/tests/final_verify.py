from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201
    
    response = client.get('/view_institution/1')
    content = response.data.decode('utf-8')
    
    print('View Institution page:', response.status_code)
    checks = [
        ('Toggle Mentors View', 'toggleMentorsView' in content),
        ('Toggle Mentees View', 'toggleMenteesView' in content),
        ('Toggle Description', 'toggleDescription' in content),
        ('No Analytics Cards', 'Statistics Cards' not in content),
        ('View All Mentors Btn', 'view-all-mentors-btn' in content),
        ('View All Mentees Btn', 'view-all-mentees-btn' in content),
        ('Toggle Description', 'toggleDescription' in content),
        ('Address toggle', 'address-cell' in content),
        ('Address full hidden', 'address-full hidden' in content),
        ('Description cell class', 'address-cell' in content),
    ]
    for name, result in checks:
        print(name + ': ' + ('PASS' if result else 'FAIL'))
    
    print()
    print('=== ALL TESTS COMPLETE ===')