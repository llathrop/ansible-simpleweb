/**
 * Ansible Web Interface - Theme Manager
 *
 * Handles loading, applying, and switching themes across the application.
 *
 * Architecture:
 * - Themes are defined as JSON files in config/themes/
 * - JSON is fetched via /api/themes endpoints
 * - Theme colors are mapped to CSS custom properties (variables)
 * - Variables are applied to document.documentElement (:root)
 * - User preference is persisted in localStorage
 *
 * Flash Prevention:
 * - CSS variables are cached in localStorage (STORAGE_KEY_VARS)
 * - An inline script in <head> applies cached vars before page renders
 * - This eliminates the flash of default theme on page load
 *
 * Usage:
 * - Theme selector dropdowns should have class="theme-select"
 * - They are automatically populated and wired up on init
 * - Manual control: ThemeManager.applyTheme('dark')
 *
 * @see config/themes/THEME_SCHEMA.md for theme JSON structure
 */

(function() {
    'use strict';

    // localStorage keys for persisting user preference
    const STORAGE_KEY = 'ansible-web-theme';           // Theme name (e.g., 'dark')
    const STORAGE_KEY_VARS = 'ansible-web-theme-vars'; // Cached CSS variables (for flash prevention)
    const DEFAULT_THEME = 'default';

    // In-memory cache for fetched theme JSON (avoids re-fetching)
    const themeCache = {};

    // List of available themes from /api/themes (populated on init)
    let availableThemes = [];

    /**
     * Map theme JSON structure to CSS custom property names
     */
    function mapThemeToCSSVariables(theme) {
        const vars = {};
        const colors = theme.colors || {};

        // Background colors
        if (colors.background) {
            vars['--bg-primary'] = colors.background.primary;
            vars['--bg-secondary'] = colors.background.secondary;
            vars['--bg-tertiary'] = colors.background.tertiary;
            vars['--bg-inverse'] = colors.background.inverse;
        }

        // Text colors
        if (colors.text) {
            vars['--text-primary'] = colors.text.primary;
            vars['--text-secondary'] = colors.text.secondary;
            vars['--text-muted'] = colors.text.muted;
            vars['--text-inverse'] = colors.text.inverse;
            vars['--text-link'] = colors.text.link;
        }

        // Border colors
        if (colors.border) {
            vars['--border-primary'] = colors.border.primary;
            vars['--border-secondary'] = colors.border.secondary;
            vars['--border-focus'] = colors.border.focus;
        }

        // Button colors
        if (colors.button) {
            if (colors.button.primary) {
                vars['--btn-primary-bg'] = colors.button.primary.background;
                vars['--btn-primary-text'] = colors.button.primary.text;
                vars['--btn-primary-hover'] = colors.button.primary.hover;
            }
            if (colors.button.secondary) {
                vars['--btn-secondary-bg'] = colors.button.secondary.background;
                vars['--btn-secondary-text'] = colors.button.secondary.text;
                vars['--btn-secondary-hover'] = colors.button.secondary.hover;
            }
            if (colors.button.disabled) {
                vars['--btn-disabled-bg'] = colors.button.disabled.background;
                vars['--btn-disabled-text'] = colors.button.disabled.text;
            }
        }

        // Status colors
        if (colors.status) {
            if (colors.status.ready) {
                vars['--status-ready-bg'] = colors.status.ready.background;
                vars['--status-ready-text'] = colors.status.ready.text;
            }
            if (colors.status.running) {
                vars['--status-running-bg'] = colors.status.running.background;
                vars['--status-running-text'] = colors.status.running.text;
            }
            if (colors.status.completed) {
                vars['--status-completed-bg'] = colors.status.completed.background;
                vars['--status-completed-text'] = colors.status.completed.text;
            }
            if (colors.status.failed) {
                vars['--status-failed-bg'] = colors.status.failed.background;
                vars['--status-failed-text'] = colors.status.failed.text;
            }
        }

        // Log colors
        if (colors.log) {
            vars['--log-bg'] = colors.log.background;
            vars['--log-text'] = colors.log.text;
            vars['--log-ok'] = colors.log.ok;
            vars['--log-changed'] = colors.log.changed;
            vars['--log-failed'] = colors.log.failed;
            vars['--log-skipped'] = colors.log.skipped;
            vars['--log-task'] = colors.log.task;
            vars['--log-play'] = colors.log.play;
            vars['--log-recap'] = colors.log.recap;
        }

        // Table colors
        if (colors.table) {
            vars['--table-header-bg'] = colors.table.header;
            vars['--table-row-hover'] = colors.table.rowHover;
            vars['--table-border'] = colors.table.border;
        }

        // Notification colors
        if (colors.notification && colors.notification.info) {
            vars['--notify-info-bg'] = colors.notification.info.background;
            vars['--notify-info-border'] = colors.notification.info.border;
            vars['--notify-info-text'] = colors.notification.info.text;
        }

        // Connection colors
        if (colors.connection) {
            vars['--connection-connected'] = colors.connection.connected;
            vars['--connection-disconnected'] = colors.connection.disconnected;
            vars['--connection-neutral'] = colors.connection.neutral;
        }

        // Shadows
        if (theme.shadows) {
            vars['--shadow-card'] = theme.shadows.card;
            vars['--shadow-card-hover'] = theme.shadows.cardHover;
        }

        return vars;
    }

    /**
     * Apply CSS variables to the document root
     */
    function applyCSSVariables(variables) {
        const root = document.documentElement;
        for (const [property, value] of Object.entries(variables)) {
            if (value) {
                root.style.setProperty(property, value);
            }
        }
    }

    /**
     * Fetch a theme JSON file
     */
    async function fetchTheme(themeName) {
        // Check cache first
        if (themeCache[themeName]) {
            return themeCache[themeName];
        }

        try {
            const response = await fetch(`/api/themes/${themeName}`);
            if (!response.ok) {
                throw new Error(`Theme not found: ${themeName}`);
            }
            const theme = await response.json();
            themeCache[themeName] = theme;
            return theme;
        } catch (error) {
            console.error(`Failed to load theme "${themeName}":`, error);
            return null;
        }
    }

    /**
     * Fetch list of available themes
     */
    async function fetchAvailableThemes() {
        try {
            const response = await fetch('/api/themes');
            if (!response.ok) {
                throw new Error('Failed to fetch themes list');
            }
            availableThemes = await response.json();
            return availableThemes;
        } catch (error) {
            console.error('Failed to load themes list:', error);
            // Return default fallback
            return [{ id: 'default', name: 'Default' }];
        }
    }

    /**
     * Get the saved theme preference
     */
    function getSavedTheme() {
        try {
            return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME;
        } catch (e) {
            // localStorage might be unavailable
            return DEFAULT_THEME;
        }
    }

    /**
     * Save theme preference and cached CSS variables
     */
    function saveTheme(themeName, variables) {
        try {
            localStorage.setItem(STORAGE_KEY, themeName);
            if (variables) {
                localStorage.setItem(STORAGE_KEY_VARS, JSON.stringify(variables));
            }
        } catch (e) {
            // localStorage might be unavailable
            console.warn('Could not save theme preference');
        }
    }

    /**
     * Apply a theme by name
     */
    async function applyTheme(themeName) {
        const theme = await fetchTheme(themeName);
        if (theme) {
            const variables = mapThemeToCSSVariables(theme);
            applyCSSVariables(variables);
            saveTheme(themeName, variables);

            // Update any theme selectors on the page
            document.querySelectorAll('.theme-select').forEach(select => {
                select.value = themeName;
            });

            // Dispatch event for any listeners
            document.dispatchEvent(new CustomEvent('themeChanged', {
                detail: { theme: themeName, data: theme }
            }));

            return true;
        }
        return false;
    }

    /**
     * Initialize theme selector dropdowns
     */
    function initializeThemeSelector(selectElement) {
        if (!selectElement) return;

        // Populate options
        selectElement.innerHTML = '';
        availableThemes.forEach(theme => {
            const option = document.createElement('option');
            option.value = theme.id;
            option.textContent = theme.name;
            selectElement.appendChild(option);
        });

        // Set current value
        selectElement.value = getSavedTheme();

        // Add change listener
        selectElement.addEventListener('change', function() {
            applyTheme(this.value);
        });
    }

    /**
     * Initialize all theme selectors on the page
     */
    function initializeAllSelectors() {
        document.querySelectorAll('.theme-select').forEach(initializeThemeSelector);
    }

    /**
     * Initialize the theme system
     */
    async function init() {
        // Fetch available themes
        await fetchAvailableThemes();

        // Apply saved theme (or default)
        const savedTheme = getSavedTheme();
        await applyTheme(savedTheme);

        // Initialize any theme selectors already in the DOM
        initializeAllSelectors();

        // Watch for dynamically added selectors
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === 1) { // Element node
                        if (node.classList && node.classList.contains('theme-select')) {
                            initializeThemeSelector(node);
                        }
                        // Check children too
                        node.querySelectorAll && node.querySelectorAll('.theme-select').forEach(initializeThemeSelector);
                    }
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // Public API
    window.ThemeManager = {
        init: init,
        applyTheme: applyTheme,
        getAvailableThemes: () => availableThemes,
        getCurrentTheme: getSavedTheme,
        initializeSelector: initializeThemeSelector
    };

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
