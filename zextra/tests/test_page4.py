from app import app

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '3'
        sess['user_id'] = 292
    
    response = client.get('/institution_all_tasks')
    content = response.data.decode('utf-8')
    
    checks = [
        ('Load Tasks button', 'Load Tasks'),
        ('Load 50 More button', 'load-50-btn'),
        ('load-more-section', 'load-more-section'),
        ('currentTaskOffset', 'currentTaskOffset'),
        ('TASK_PAGE_SIZE', 'TASK_PAGE_SIZE = 50'),
        ('loadMoreTasks function', 'loadMoreTasks'),
        ('fetch API call', 'fetch('),
        ('has_more handling', 'has_more'),
    ]
    
    for name, check in checks:
        found = check in content
        print(f'{name}: {"PASS" if found else "FAIL"}')