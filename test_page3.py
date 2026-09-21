from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '3'
        sess['user_id'] = 292
    
    response = client.get('/institution_all_tasks')
    content = response.data.decode('utf-8')
    print('Status:', response.status_code)
    print('Content length:', len(content))
    print('First 500 chars:', content[:500])