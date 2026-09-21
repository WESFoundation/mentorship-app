from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'info@wazireducationsocity.com'
        sess['user_type'] = '0'
        sess['user_id'] = 201
    
    response = client.get('/supervisor_all_mentorships')
    content = response.data.decode('utf-8')
    
    # Check for different statuses
    if 'data-status="pending"' in content:
        pending = content.count('data-status="pending"')
        print(f'Pending requests: {pending}')
    if 'data-status="approved"' in content:
        approved = content.count('data-status="approved"')
        print(f'Approved requests: {approved}')
    if 'data-status="rejected"' in content:
        rejected = content.count('data-status="rejected"')
        print(f'Rejected requests: {rejected}')
    
    # Check filter elements exist
    if 'statusFilter' in content:
        print('Status filter dropdown: PRESENT')
    if 'durationFilter' in content:
        print('Duration filter dropdown: PRESENT')
    if 'typeFilter' in content:
        print('Type filter dropdown: PRESENT')
    if 'mentorshipSearch' in content:
        print('Search input: PRESENT')