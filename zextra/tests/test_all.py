from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '3'
        sess['user_id'] = 201
    
    # Test institution page
    response = client.get('/institution')
    content = response.data.decode('utf-8')
    
    checks = [
        ('3 dots actions', 'fa-ellipsis-v' in content),
        ('toggleDropdown', 'toggleDropdown' in content),
        ('description see more', 'See more' in content and 'toggleDescription' in content),
        ('location see more', 'toggleLocation' in content),
    ]
    
    print('--- Institution Page Checks ---')
    for name, found in checks:
        print(f'{name}: {"PASS" if found else "FAIL"}')
    
    # Test view_institution
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '3'
        sess['user_id'] = 292
    
    response = client.get('/view_institution/1')
    content = response.data.decode('utf-8')
    
    checks2 = [
        ('mentors toggle', 'toggleMentorsView' in content),
        ('mentees toggle', 'toggleMenteesView' in content),
        ('description toggle', 'toggleDescription' in content),
        ('no analytics cards', 'Statistics Cards' not in content),
        ('mentors view all', 'toggleMentorsView' in content),
        ('mentees view all', 'toggleMenteesView' in content),
    ]
    
    print('\n--- View Institution Page Checks ---')
    for name, found in checks2:
        print(f'{name}: {"PASS" if found else "FAIL"}')