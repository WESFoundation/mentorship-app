with open('templates/certificate.html', 'r') as f:
    content = f.read()

# Find the renderCheckboxes function and update the connections rendering
old = "return item.name + '<span class=\"item-meta\">' + item.type + '</span>';"

new = """var corporateBadge = item.is_corporate ? '<span class=\"corporate-badge-wrapper\" style=\"display:inline-flex;margin-left:6px;\" title=\"Corporate Verified\"><svg class=\"corporate-badge-icon\" width=\"14\" height=\"14\" fill=\"currentColor\" viewBox=\"0 0 20 20\"><path fill-rule=\"evenodd\" d=\"M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z\" clip-rule=\"evenodd\"/></svg></span>' : '';
                return item.name + corporateBadge + '<span class=\"item-meta\">' + item.type + '</span>';"""

if old in content:
    content = content.replace(old, new)
    with open('templates/certificate.html', 'w') as f:
        f.write(content)
    print('Updated certificate.html')
else:
    print('Pattern not found')