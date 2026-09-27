from app import app

with app.test_client() as client:
    # Test Institution page as supervisor
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201
    
    response = client.get('/institution')
    content = response.data.decode('utf-8')
    
    print('=== INSTITUTION PAGE ===')
    print('Status:', response.status_code)
    checks = [
        ('3 dots icon', 'fa-ellipsis-v' in content),
        ('toggleDropdown function', 'toggleDropdown' in content),
        ('Description See More', 'toggleDescription' in content),
        ('Location See More', 'toggleLocation' in content),
        ('Dropdown positioning (fixed)', "dropdown.style.position = 'fixed'" in content),
        ('See more/less text', 'See less' in content),
        ('Description cell class', 'description-cell' in content),
        ('Location cell class', 'location-cell' in content),
    ]
    for name, found in checks:
        print(f'  {name}: {"PASS" if found else "FAIL"}')
    
    # Test view_institution page as supervisor
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201
    
    response = client.get('/view_institution/1')
    content = response.data.decode('utf-8')
    
    print('\n=== VIEW INSTITUTION PAGE ===')
    print('Status:', response.status_code)
    checks2 = [
        ('Toggle Mentors View', 'toggleMentorsView' in content),
        ('Toggle Mentees View', 'toggleMenteesView' in content),
        ('Toggle Description', 'toggleDescription' in content),
        ('No Analytics Cards', 'Statistics Cards' not in content),
        ('View All Mentors Btn', 'view-all-mentors-btn' in content),
        ('View All Mentees Btn', 'view-all-mentees-btn' in content),
        ('Description toggle in location', 'toggleDescription' in content),
        ('Address toggle', 'address-cell' in content),
        ('Address full hidden', 'address-full hidden' in content),
        ('Description cell class', 'address-cell' in content),
    ]
    print('\n=== VIEW INSTITUTION PAGE ===')
    print('Status:', response.status_code)
    for name, found in checks2:
        print(f'  {name}: {"PASS" if found else "FAIL"}')
    
    print('\n=== ALL TESTS COMPLETE ===')