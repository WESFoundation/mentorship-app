with open('templates/supervisor/view_institution.html', 'r') as f:
    content = f.read()

# Just do a simple string replace for the specific line
old = "btn.textContent = 'View All {{ institution_mentees|length }} Mentees';"
new = "btn.textContent = 'View All ' + menteeCount + ' Mentees';"

content = content.replace(old, new)

with open('templates/supervisor/view_institution.html', 'w') as f:
    f.write(content)
print('Done')