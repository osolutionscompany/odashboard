{
    'name': 'Odashboard',
    'version': '1.0',
    'category': 'Dashboard',
    'summary': 'Odoo dashboard application',
    'description': """
        This module provides dashboard for Odoo.:
    """,
    'author': 'OSolutions',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        # Security
        'security/odash_security.xml',
        'security/ir.model.access.csv',

        # Data
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',

        # Views
        'views/res_config_settings_views.xml',
        'views/dashboard_views.xml',
        'views/odash_security_group_views.xml',
        'views/odash_config_views.xml',
        'views/menu_items.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odashboard/static/src/js/odash_iframe_widget.js',
            'odashboard/static/src/xml/odash_iframe_widget.xml'
        ],
    },
    'license': 'Other proprietary',
    'application': True,
    'installable': True,
    'auto_install': False,
}
