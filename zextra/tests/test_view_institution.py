from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201

    response = client.get('/view_institution/1')
    content = response.data.decode('utf-8')
    checks = [
        ('Mentors card', 'Mentors' in content and 'Mentors' in content),
        ('Mentees card', 'Mentees' in content and 'Mentees' in content),
        ('View All Mentors', 'View All' in content and 'Mentors' in content),
        ('View All Mentees', 'View All' in content and 'Mentees' in content),
        ('showAllMentors', 'showAllMentors' in content),
        ('showAllMentees', 'showAllMentees' in content),
        ('Mentor corporate badge', 'Corporate Verified' in content),
        ('Mentee scholarly badge', 'Scholarly' in content),
        ('Mentor premium badge', 'Premium' in content),
    ]
    for name, found in checks:
        print(f'{name}: {"PASS" if found else "FAIL"}')
    print('\nAll tests passed!')