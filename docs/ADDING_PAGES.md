# Adding Custom Pages

This document explains how to add new pages to the web interface. The navigation is centralized so that adding a page updates all pages automatically.

## Steps

1. **Add the nav entry** in `web/nav.py`:
   - Edit `NAV_SECTIONS`
   - Add `{'url': '/your-page', 'label': 'Your Page'}` to the appropriate section (Execution, Logs & Data, or System)
   - Or create a new section

2. **Add the route** in `web/app.py`:
   ```python
   @app.route('/your-page')
   def your_page():
       return render_template('your_page.html', ...)
   ```

3. **Create the template** extending `base.html`:
   ```html
   {% extends "base.html" %}
   {% block title %}Your Page | Ansible Web Interface{% endblock %}

   {% block content %}
   <div class="container">
       <h1>Your Page</h1>
       ...
   </div>
   {% endblock %}
   ```

4. Pages that need WebSocket (e.g. for live updates) can use `window.__socket` provided by the base layout.

## Nav Structure

Navigation is defined in `web/nav.py` as `NAV_SECTIONS`: top-level sections (tabs) with their left-panel links. The active section and page are determined from the request path. Sub-pages (e.g. `/schedules/new`) highlight the parent page (Schedules) in the left nav.
