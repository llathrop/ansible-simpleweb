"""
Navigation structure for the web UI.

Centralized definition of top tabs and left-side panel links. Pages extending
base.html receive this via template context. To add a new page:
  1. Add an entry to NAV_SECTIONS below
  2. Add the corresponding route in app.py
  3. Create the template extending base.html

For user-added custom pages, add entries to NAV_SECTIONS (or extend via
configuration in the future). The structure is the single source of truth;
all pages pick up changes automatically.
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
]


def get_nav_context(path: str) -> dict:
    """
    Return template context for navigation: nav_sections, active_section_id, active_page_url.
    Determines active section and page from the request path.
    Uses longest prefix match so /schedules/new highlights Schedules.
    """
    active_section_id = None
    active_page_url = None
    path = path.rstrip('/') or '/'
    best_match_len = -1

    for section in NAV_SECTIONS:
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
        'nav_sections': NAV_SECTIONS,
        'active_section_id': active_section_id or (NAV_SECTIONS[0]['id'] if NAV_SECTIONS else None),
        'active_page_url': active_page_url,
    }
