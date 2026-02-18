"""
Navigation structure for the web UI.

Centralized definition of top tabs and left-side panel links. Pages extending
base.html receive this via template context.

Adding a new page:
  1. Add an entry to NAV_SECTIONS below (choose section, add {url, label})
  2. Add the route in app.py (e.g. @app.route('/mypage'))
  3. Create the template extending base.html
  4. All existing pages automatically show the new nav link; no per-page edits.

Custom/user pages: Add entries to NAV_SECTIONS. The structure is the single
source of truth; all pages pick up changes automatically.
"""

# Top-level sections (tabs) with their left-nav pages.
# url: exact path or prefix (e.g. /logs matches /logs/xyz)
# section_id: used for tab highlighting
NAV_SECTIONS = [
    {
        'id': 'execution',
        'label': 'Execution',
        'pages': [
            {'url': '/', 'label': 'Batch Execution'},
            {'url': '/playbooks', 'label': 'Playbooks'},
            {'url': '/schedules', 'label': 'Schedules'},
        ],
    },
    {
        'id': 'data',
        'label': 'Logs & Data',
        'pages': [
            {'url': '/logs', 'label': 'All Logs'},
            {'url': '/inventory', 'label': 'Inventory'},
            {'url': '/cmdb', 'label': 'CMDB'},
            {'url': '/storage', 'label': 'Storage'},
        ],
    },
    {
        'id': 'system',
        'label': 'System',
        'pages': [
            {'url': '/config', 'label': 'Config'},
            {'url': '/cluster', 'label': 'Cluster'},
            {'url': '/agent', 'label': 'Agent'},
        ],
    },
    {
        'id': 'admin',
        'label': 'Admin',
        'pages': [
            {'url': '/users', 'label': 'Users'},
        ],
        'admin_only': True,
    },
]


def get_nav_context(path: str, user=None) -> dict:
    """
    Return template context for navigation: nav_sections, active_section_id, active_page_url.
    Determines active section and page from the request path.
    Uses longest prefix match so /schedules/new highlights Schedules.
    """
    active_section_id = None
    active_page_url = None
    path = path.rstrip('/') or '/'
    best_match_len = -1

    # Filter sections based on user permissions
    is_admin = False
    if user:
        from authz import check_permission
        is_admin = check_permission(user, 'users:*')

    visible_sections = [
        s for s in NAV_SECTIONS
        if not s.get('admin_only') or is_admin
    ]

    for section in visible_sections:
        for page in section['pages']:
            page_url = page['url'].rstrip('/') or '/'
            if path == page_url:
                match_len = len(page_url)
            elif page_url == '/' and path.startswith('/'):
                match_len = 1
            elif page_url != '/' and path.startswith(page_url + '/'):
                match_len = len(page_url)
            else:
                continue
            if match_len > best_match_len:
                best_match_len = match_len
                active_section_id = section['id']
                active_page_url = page['url']

    return {
        'nav_sections': visible_sections,
        'active_section_id': active_section_id or (visible_sections[0]['id'] if visible_sections else None),
        'active_page_url': active_page_url,
        'current_user': user,
    }
