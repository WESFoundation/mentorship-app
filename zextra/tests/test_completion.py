from app import app, db, MenteeTask, MenteeFeedback, compute_task_progress_status, TaskRating

with app.app_context():
    task = MenteeTask.query.filter_by(status='pending').first()
    print(f'Task {task.id} (no feedback):')
    print(f'  Status: {compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id)}')
    
    fb = MenteeFeedback(
        mentee_id=task.mentee_id,
        task_id=task.id,
        task_type='master',
        rating=4,
        text='Great session!',
    )
    db.session.add(fb)
    db.session.commit()
    
    print('After adding mentee feedback:')
    print(f'  Status: {compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id)}')
    
    rating = TaskRating(task_id=task.id, task_type='master', rating=5)
    db.session.add(rating)
    db.session.commit()
    
    print('After adding mentor rating:')
    print(f'  Status: {compute_task_progress_status("master", task.id, task.mentee_id, task.mentor_id)}')
    
    db.session.delete(fb)
    db.session.delete(db.session.get(TaskRating, rating.id))
    db.session.commit()
    print('Cleaned up')