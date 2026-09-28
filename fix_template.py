with open('templates/supervisor/view_institution.html', 'r') as f:
    content = f.read()

# Fix toggleMentorsView
old1 = '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentors|length }} Mentors';
    }
}'''

new1 = '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    const mentorCount = document.querySelectorAll('.view-mentor-profile-btn').length;
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All ' + mentorCount + ' Mentors';
    }
}'''

content = open('templates/supervisor/view_institution.html', 'r').read()
content = content.replace(
    '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentors|length }} Mentors';
    }
}''',
    '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    const mentorCount = document.querySelectorAll('.view-mentor-profile-btn').length;
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All ' + mentorCount + ' Mentors';
    }
}""")

# Fix toggleMenteesView
old2 = '''function toggleMenteesView() {
    const container = document.querySelectorAll('.space-y-3.max-h-80.overflow-y-auto')[1];
    const btn = document.getElementById('view-all-mentees-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentees|length }} Mentees';
    }
}'''

new2 = '''function toggleMenteesView() {
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
}'''

with open('templates/supervisor/view_institution.html', 'r') as f:
    content = f.read()

content = content.replace(
    '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentors|length }} Mentors';
    }
}''',
    '''function toggleMentorsView() {
    const container = document.querySelector('.space-y-3.max-h-80.overflow-y-auto');
    const btn = document.getElementById('view-all-mentors-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    const mentorCount = document.querySelectorAll('.view-mentor-profile-btn').length;
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All ' + mentorCount + ' Mentors';
    }
}''')

# Fix toggleMenteesView
content = content.replace(
    '''function toggleMenteesView() {
    const container = document.querySelectorAll('.space-y-3.max-h-80.overflow-y-auto')[1];
    const btn = document.getElementById('view-all-mentees-btn');
    const isCollapsed = container.classList.contains('max-h-80');
    
    if (isCollapsed) {
        container.classList.remove('max-h-80');
        btn.textContent = 'Show Less';
    } else {
        container.classList.add('max-h-80');
        btn.textContent = 'View All {{ institution_mentees|length }} Mentees';
    }
}''',
    '''function toggleMenteesView() {
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
}""")

with open('templates/supervisor/view_institution.html', 'w') as f:
    f.write(content)
print('Done')