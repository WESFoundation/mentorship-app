with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find the api_export_institution_data function and add new endpoint after it
new_endpoint = '''

@app.route("/api/institution_users/<int:institution_id>", methods=["GET"])
def api_institution_users(institution_id):
    """Get all users (mentors and mentees) for an institution.
    Returns list of users with their details including is_corporate flag."""
    # Verify institution exists
    institution = Institution.query.get(institution_id)
    if not institution:
        return jsonify({"error": "Institution not found"}), 404
    
    # Get all users linked to this institution
    users = User.query.filter_by(institution_id=institution_id).all()
    
    users_data = []
    for user in users:
        users_data.append({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "user_type": user.user_type,
            "user_type_label": "Mentor" if user.user_type == "1" else ("Mentee" if user.user_type == "2" else "Institution"),
            "institution_id": user.institution_id,
            "institution_name": user.institution,
            "is_corporate": getattr(user, 'is_corporate', False),
            "profile_picture": user.profile_picture,
            "created_at": user.created_at.isoformat() if user.created_at else None
        })
    
    return jsonify({
        "institution_id": institution_id,
        "institution_name": institution.name,
        "users": users_data,
        "total_users": len(users_data)
    })

'''

# Find the end of api_export_institution_data function
idx = content.find('def api_export_institution_data')
if idx >= 0:
    rest = content[idx:]
    next_def = rest.find('\ndef ', 1)
    next_route = rest.find('\n@app.route', 1)
    if next_def >= 0 and (next_route < 0 or next_def < next_route):
        end_idx = next_def
    else:
        end_idx = next_route
    if end_idx > 0:
        insert_pos = idx + end_idx
        content = content[:insert_pos] + new_endpoint + content[insert_pos:]
        with open('app.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('Endpoint added successfully')
    else:
        print('Could not find insertion point')
else:
    print('Function not found')