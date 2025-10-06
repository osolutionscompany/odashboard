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
        'mail',
    ],
    'external_dependencies': {
        'python': ['PyPDF2'],
    },
    'data': [
        # Security
        'security/odash_security.xml',
        'security/ir.model.access.csv',

        # Data
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'data/ir_cron_pdf_reports.xml',
        'data/mail_template_pdf_report.xml',

        # Views
        'views/res_config_settings_views.xml',
        'views/dashboard_views.xml',
        'views/odash_security_group_views.xml',
        'views/odash_config_views.xml',
        'views/dashboard_public_views.xml',
        'views/odash_dashboard_views.xml',
        'views/odash_pdf_report_views.xml',
        # Wizards
        'wizards/odash_config_import_wizard_views.xml',
        'wizards/odash_config_export_wizard_views.xml',
        # Menu
        'views/menu_items.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odashboard/static/src/css/odash_iframe_widget.css',
            'odashboard/static/src/js/odash_iframe_widget.js',
            'odashboard/static/src/xml/odash_iframe_widget.xml'
        ],
    },
    'license': 'Other proprietary',
    'application': True,
    'installable': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
}
