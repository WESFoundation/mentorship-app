with open('templates/supervisor/view_institution.html', 'r') as f:
    content = f.read()

# Fix toggleMenteesView - note the typo: queryselectorAll (lowercase s)
old2 = """function toggleMenteesView() {
    const container = document.queryselectorAll('.space-y-3.max-h-80.overflow-y-auto')[1];
    const btn = document.getElementById('view-all-mentees-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentees|length }} Mentees';
    }
}"""

new2 = """function toggleMenteesView() {
    const container = document.querySelectorAll('.space-y-3.max-h-80.overflow-y-auto')[1];
    const btn = document.getElementById('view-all-mentees-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    const menteeCount = document.querySelectorAll('.view-mentee-profile-btn').length;
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All ' + menteeCount + ' Mentees';
    }
}"""

content = content.replace(old2, new2)

with open('templates/supervisor/view_institution.html', 'w') as f:
    f.write(content)
print('Done')