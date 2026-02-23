{
    'name': 'O\'Dashboard',
    'version': '18.0.2.0.0',
    'category': 'Technical',
    'summary': 'Expose database schema and query endpoints for ODashboard',
    'description': """
        This module exposes REST endpoints for ODashboard:
        - GET /odashboard/schema - Returns database schema
        - POST /odashboard/query - Executes SELECT queries
        - POST /odashboard/rotate-api-key - Rotate API key (called by ODashboard)

        Authentication is done via API keys (Bearer token) for schema/query endpoints.
        The rotate-api-key endpoint uses instance_key authentication.

        Configure the connection in Settings > ODashboard.
    """,
    'author': 'OSolutions',
    'website': 'https://osolutions.com',
    'depends': ['base', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'views/api_key_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odashboard_v2static/src/css/odashboard_action.css',
            'odashboard_v2static/src/js/odashboard_action.js',
            'odashboard_v2static/src/xml/odashboard_action.xml',
        ],
    },
    'license': 'LGPL-3',
    'application': True,
    'installable': True,
    'auto_install': False,
}
