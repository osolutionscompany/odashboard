import json

from odoo import fields, models


class OdashConfig(models.Model):
    _name = 'odash.config'
    _description = 'Odashboard config'
    _rec_name = 'config_id'

    is_page_config = fields.Boolean(string='Is Page Config', default=False)
    config_id = fields.Char(string='Config ID')
    config = fields.Json(string='Config')

    def clean_unused_config(self):
        pages = self.env['odash.config'].sudo().search([('is_page_config', '=', True)])
        configs = self.env['odash.config'].sudo().search([('is_page_config', '=', False)])

        total_pages = " ".join([json.dumps(page.config) for page in pages])

        for config in configs:
            if config.config_id not in total_pages:
                config.sudo().unlink()
