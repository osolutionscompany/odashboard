from odoo import api, fields, models


class OdashConfig(models.Model):
    _name = 'odash.config'
    _description = 'Odashboard config'
    _rec_name = 'config_id'

    is_page_config = fields.Boolean(string='Is Page Config', default=False)
    config_id = fields.Char(string='Config ID')
    config = fields.Json(string='Config')
