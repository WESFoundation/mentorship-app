with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Update the mentor connections section (around line 46-63)
old_mentor_connections = '''        for mr in active_mentorships:
            mentee = User.query.get(mr.mentee_id)
            if mentee and mentee.id not in seen_mentee_ids:
                seen_mentee_ids.add(mentee.id)
                connections_list.append({
                    "id": mr.id,
                    "name": mentee.name,
                    "type": "mentee"
                })'''

new_mentor_connections = '''        for mr in active_mentorships:
            mentee = User.query.get(mr.mentee_id)
            if mentee and mentee.id not in seen_mentee_ids:
                seen_mentee_ids.add(mentee.id)
                connections_list.append({
                    "id": mr.id,
                    "name": mentee.name,
                    "type": "mentee",
                    "is_corporate": getattr(mentee, 'is_corporate', False)
                })'''

content = content.replace(old_mentor_connections, new_mentor_connections)

# Update the mentee tasks connections (around line 53-63)
old_mentor_tasks = '''        # Also include mentees linked via MenteeTask if not already in list
        mentee_tasks = MenteeTask.query.filter_by(mentor_id=user.id).all()
        for t in mentee_tasks:
            if t.mentee_id and t.mentee_id not in seen_mentee_ids:
                mentee = User.query.get(t.mentee_id)
                if mentee:
                    seen_mentee_ids.add(t.mentee_id)
                    connections_list.append({
                        "id": f"t_{t.id}",
                        "name": mentee.name,
                        "type": "mentee"
                    })'''

new_mentor_tasks = '''        # Also include mentees linked via MenteeTask if not already in list
        mentee_tasks = MenteeTask.query.filter_by(mentor_id=user.id).all()
        for t in mentee_tasks:
            if t.mentee_id and t.mentee_id not in seen_mentee_ids:
                mentee = User.query.get(t.mentee_id)
                if mentee:
                    seen_mentee_ids.add(t.mentee_id)
                    connections_list.append({
                        "id": f"t_{t.id}",
                        "name": mentee.name,
                        "type": "mentee",
                        "is_corporate": getattr(mentee, 'is_corporate', False)
                    })'''

content = content.replace(old_mentor_tasks, new_mentor_tasks)

# Update the mentee connections section (around line 117-138)
old_mentee_connections = '''        for mr in active_mentorships:
            mentor = User.query.get(mr.mentor_id)
            if mentor and mentor.id not in seen_mentor_ids:
                seen_mentor_ids.add(mentor.id)
                connections_list.append({
                    "id": mr.id,
                    "name": mentor.name,
                    "type": "mentor"
                })'''

new_mentee_connections = '''        for mr in active_mentorships:
            mentor = User.query.get(mr.mentor_id)
            if mentor and mentor.id not in seen_mentor_ids:
                seen_mentor_ids.add(mentor.id)
                connections_list.append({
                    "id": mr.id,
                    "name": mentor.name,
                    "type": "mentor",
                    "is_corporate": getattr(mentor, 'is_corporate', False)
                })'''

content = content.replace(old_mentee_connections, new_mentee_connections)

# Update the mentee tasks connections (around line 128-138)
old_mentee_tasks = '''        # Also include mentors linked via MenteeTask if not already in list
        mentee_tasks = MenteeTask.query.filter_by(mentee_id=user.id).all()
        for t in mentee_tasks:
            if t.mentor_id and t.mentor_id not in seen_mentor_ids:
                mentor = User.query.get(t.mentor_id)
                if mentor:
                    seen_mentor_ids.add(t.mentor_id)
                    connections_list.append({
                        "id": f"t_{t.id}",
                        "name": mentor.name,
                        "type": "mentor"
                    })'''

new_mentee_tasks = '''        # Also include mentors linked via MenteeTask if not already in list
        mentee_tasks = MenteeTask.query.filter_by(mentee_id=user.id).all()
        for t in mentee_tasks:
            if t.mentor_id and t.mentor_id not in seen_mentor_ids:
                mentor = User.query.get(t.mentor_id)
                if mentor:
                    seen_mentor_ids.add(t.mentor_id)
                    connections_list.append({
                        "id": f"t_{t.id}",
                        "name": mentor.name,
                        "type": "mentor",
                        "is_corporate": getattr(mentor, 'is_corporate', False)
                    })'''

content = content.replace(old_mentee_tasks, new_mentee_tasks)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated certificate route with is_corporate')