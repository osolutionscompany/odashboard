import json

from odoo import fields, models, api


class OdashConfig(models.Model):
    _name = 'odash.config'
    _description = 'Odashboard config'
    _rec_name = 'config_id'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    sequence = fields.Integer(string='Sequence', default=1)

    access_summary = fields.Char(string='Access summary', compute='_compute_access_summary')

    is_page_config = fields.Boolean(string='Is Page Config', default=False)
    config_id = fields.Char(string='Config ID')
    config = fields.Json(string='Config')

    security_group_ids = fields.Many2many('odash.security.group', string='Security Groups')
    user_ids = fields.Many2many('res.users', string='Users')

    def clean_unused_config(self):
        pages = self.env['odash.config'].sudo().search([('is_page_config', '=', True)])
        configs = self.env['odash.config'].sudo().search([('is_page_config', '=', False)])

        total_pages = " ".join([json.dumps(page.config) for page in pages])

        for config in configs:
            if config.config_id not in total_pages:
                config.sudo().unlink()

    @api.depends('config')
    def _compute_name(self):
        for record in self:
            record.name = record.config.get("title", "Unnamed")

    @api.depends('security_group_ids', 'user_ids')
    def _compute_access_summary(self):
        for record in self:
            if not record.security_group_ids and not record.user_ids:
                record.access_summary = "All users"
            else:
                users_from_groups = record.security_group_ids.mapped('user_ids')
                record.access_summary = f"Custom access: {len(record.security_group_ids)} groups ({len(users_from_groups)} distinct users), {len(record.user_ids)} directly assigned users"
                
