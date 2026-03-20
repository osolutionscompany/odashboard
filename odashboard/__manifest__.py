{
    'name': "O'Dashboard V2",
    'version': '17.0.2.0.0',
    'category': 'Technical',
    'summary': "Expose database schema and query endpoints for O'Dashboard",
    'description': """
This module exposes REST endpoints for O'Dashboard:
- GET /odashboard/schema - Returns database schema
- POST /odashboard/query - Executes SELECT queries
- POST /odashboard/rotate-api-key - Rotate API key (called by O'Dashboard)

Authentication is done via API keys (Bearer token) for schema/query endpoints.
The rotate-api-key endpoint uses instance_key authentication.

Configure the connection in Settings > O'Dashboard.
    """,
    'author': "O'Solutions Company",
    'website': 'https://odashboard.app',
    'depends': ['base', 'web'],
    'data': [
        # Data
        'data/ir_config_parameter_data.xml',

        # Security
        'security/odash_security.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',

        # Views
        'views/api_key_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odashboard/static/src/js/odashboard_action.js',
            'odashboard/static/src/css/odashboard_action.css',
            'odashboard/static/src/xml/odashboard_action.xml',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/icon.png',
        'static/description/youtube-link.png',
    ],
    'license': 'OPL-1',
    'application': True,
    'installable': True,
    'auto_install': False,
}
