from app import app, db, MenteeTask, MenteeFeedback, compute_task_progress_status, _has_mentee_feedback

with app.app_context():
    task = MenteeTask.query.filter_by(status='pending').first()
    if task:
        print(f'Task {task.id} (no feedback):')
        status = compute_task_progress_status('master', task.id, task.mentee_id, task.mentor_id)
        print(f'  Status: {status}')
        has_fb = _has_mentee_feedback('master', task.id, task.mentee_id)
        print(f'  Has feedback: {has_fb}')
        
        fb = MenteeFeedback(
            mentee_id=task.mentee_id,
            task_id=task.id,
            task_type='master',
            rating=4,
            text='Great session!',
        )
        db.session.add(fb)
        db.session.commit()
        
        print('\nAfter adding feedback:')
        has_fb = _has_mentee_feedback('master', task.id, task.mentee_id)
        print(f'  Has feedback: {has_fb}')
        status = compute_task_progress_status('master', task.id, task.mentee_id, task.mentor_id)
        print(f'  Status: {status}')
        
        db.session.delete(fb)
        db.session.commit()