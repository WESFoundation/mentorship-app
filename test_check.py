from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '3'
        sess['user_id'] = 292
    
    response = client.get('/institution_all_tasks')
    content = response.data.decode('utf-8')
    
    checks = [
        ('jQuery CDN', 'jquery' in content),
        ('loadMoreTasks', 'loadMoreTasks' in content),
        ('$.ajax', '$.ajax' in content),
        ('currentTaskOffset', 'currentTaskOffset' in content),
        ('TASK_PAGE_SIZE', 'TASK_PAGE_SIZE = 50' in content),
        ('load-more-section', 'load-more-section' in content),
        ('load-50-btn', 'load-50-btn' in content),
        ('$.ajax call', '$.ajax' in content),
    ]
    
    for name, found in checks:
        print(f'{name}: {"PASS" if found else "FAIL"}')