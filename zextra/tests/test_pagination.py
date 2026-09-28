from app import app
import json

with app.test_client() as client:
    with client.session_transaction() as sess:
        sess['email'] = 'esha01.wes@gmail.com'
        sess['user_type'] = '3'
        sess['user_id'] = 292
    
    # Click 1
    response = client.get('/get_institution_tasks_data?offset=0&limit=50')
    data = json.loads(response.data)
    print('Click 1 (offset=0):', len(data["tasks"]), 'tasks, has_more=', data["has_more"])
    
    # Click 2
    response = client.get('/get_institution_tasks_data?offset=50&limit=50')
    data = json.loads(response.data)
    print('Click 2 (offset=50):', len(data["tasks"]), 'tasks, has_more=', data["has_more"])
    
    # Click 3
    response = client.get('/get_institution_tasks_data?offset=100&limit=50')
    data = json.loads(response.data)
    print('Click 3 (offset=100):', len(data["tasks"]), 'tasks, has_more=', data["has_more"])
    
    # With filter
    response = client.get('/get_institution_tasks_data?offset=0&limit=50&status=done')
    data = json.loads(response.data)
    print('Filter status=done:', len(data["tasks"]), 'tasks, total=', data["total"])
    
    response = client.get('/get_institution_tasks_data?offset=0&limit=50&status=pending')
    data = json.loads(response.data)
    print('Filter status=pending:', len(data["tasks"]), 'tasks, total=', data["total"])