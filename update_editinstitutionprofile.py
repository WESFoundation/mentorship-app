with open('app.py', 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find the section after updating corporate status for all users and add refresh for current user
old = '''            # Update corporate status for all users under this institution
            if institution_details.email_domain:
                institution_users = User.query.filter_by(institution_id=institution_details.id).all()
                for u in institution_users:
                    u.is_corporate = check_corporate_email(u.email, institution_details)
                db.session.commit()
            else:
                # Clear corporate status if no email domain set
                institution_users = User.query.filter_by(institution_id=institution_details.id).all()
                for u in institution_users:
                    u.is_corporate = False
                db.session.commit()
            flash("Institution profile updated successfully!", "success")'''

new = '''            # Update corporate status for all users under this institution
            if institution_details.email_domain:
                institution_users = User.query.filter_by(institution_id=institution_details.id).all()
                for u in institution_users:
                    u.is_corporate = check_corporate_email(u.email, institution_details)
                db.session.commit()
            else:
                # Clear corporate status if no email domain set
                institution_users = User.query.filter_by(institution_id=institution_details.id).all()
                for u in institution_users:
                    u.is_corporate = False
                db.session.commit()
            
            # Also refresh current user's corporate status (covers edge cases)
            refresh_user_corporate_status(user)
            
            flash("Institution profile updated successfully!", "success")'''

content = content.replace(old, new)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated editinstitutionprofile with refresh_user_corporate_status')