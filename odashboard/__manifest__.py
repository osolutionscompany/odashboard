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
        # Data
        'data/ir_config_parameter.xml',

        # Security
        'security/ir.model.access.csv',

        # Views
        'views/res_config_settings_views.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
