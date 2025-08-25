import urllib.parse
import string
import random
import uuid
import requests
from datetime import datetime

from odoo import models, fields, api
from odoo.addons.website_generator.models import page


def generate_random_string(n):
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choice(characters) for _ in range(n))
    return random_string


class Dashboard(models.Model):
    _name = "odash.dashboard"
    _description = "Dashboard accesses"

    name = fields.Char(default='Odashboard')

    user_id = fields.Many2one("res.users", string="User", index=True)
    allowed_company_ids = fields.Many2many("res.company", string="Companies")
    page_id = fields.Many2one("odash.config", string="Page")

    connection_url = fields.Char(string="URL")
    token = fields.Char(string="Token")
    config = fields.Json(string="Config")

    last_authentication_date = fields.Datetime(string="Last Authentication Date")

    @api.model
    def update_auth_token(self):
        uuid_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')
        key_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.key')
        api_endpoint = self.env['ir.config_parameter'].sudo().get_param('odashboard.api.endpoint')
        data_raw = requests.get(f"{api_endpoint}/api/odash/access/{uuid_param}/{key_param}")
        if data_raw.status_code == 200:
            data = data_raw.json()
            self.env['ir.config_parameter'].sudo().set_param('odashboard.api.token', data['token'])
            self.env['ir.config_parameter'].sudo().set_param('odashboard.plan', data['plan'])

    def get_public_dashboard(self, page_id=False):
        user_id = self.env.ref('base.public_user').id
        dashboard_id = self.search([('user_id', '=', user_id), ('page_id', '=', page_id)], limit=1)

        if not dashboard_id:
            dashboard_id = self.create({
                'user_id': user_id,
                'page_id': page_id,
            })

        config_model = self.env['ir.config_parameter'].sudo()
        base_url = config_model.get_param('web.base.url')
        connection_url = config_model.get_param('odashboard.connection.url', 'https://app.odashboard.app')
        new_token = generate_random_string(64) if not dashboard_id.token else dashboard_id.token
        companies_ids = self.env['res.company'].search([])

        new_connection_url = f"{connection_url}/public?token={new_token}|{urllib.parse.quote(f'{base_url}/api', safe='')}|{uuid.uuid4()}|0|0|viewer|{','.join(str(id) for id in companies_ids.ids)}"

        dashboard_id.write({
            "token": new_token,
            "connection_url": new_connection_url,
            "last_authentication_date": datetime.now(),
            "allowed_company_ids": [(6, 0, companies_ids.ids)]
        })
        return new_connection_url

    def get_dashboard_for_user(self):
        user_id = self.env.user.id
        dashboard_id = self.search([('user_id', '=', user_id)], limit=1)

        if not dashboard_id:
            dashboard_id = self.create({
                'user_id': user_id
            })

        dashboard_id._refresh()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Dashboard',
            'res_model': 'odash.dashboard',
            'view_mode': 'form',
            'res_id': dashboard_id.id,
            'view_id': self.env.ref('odashboard.view_dashboard_custom_iframe').id,
            'target': 'current',
        }

    def ask_refresh(self, companies_ids):
        config_model = self.env['ir.config_parameter'].sudo()
        base_url = config_model.get_param('web.base.url')
        connection_url = config_model.get_param('odashboard.connection.url', 'https://app.odashboard.app')
        new_token = generate_random_string(64) if not self.token else self.token

        new_connection_url = f"{connection_url}?token={new_token}|{urllib.parse.quote(f'{base_url}/api', safe='')}|{uuid.uuid4()}|{self.user_id.id}|{self.env.user.partner_id.id}|{'editor' if self.user_id.has_group('odashboard.group_odashboard_editor') else 'viewer'}|{','.join(str(id) for id in companies_ids)}"
        self.write({
            "token": new_token,
            "connection_url": new_connection_url,
            "last_authentication_date": datetime.now(),
            "allowed_company_ids": [(6, 0, companies_ids)]
        })

    def _refresh(self):
        config_model = self.env['ir.config_parameter'].sudo()
        base_url = config_model.get_param('web.base.url')
        connection_url = config_model.get_param('odashboard.connection.url', 'https://app.odashboard.app')
        new_token = generate_random_string(64) if not self.token else self.token

        new_connection_url = f"{connection_url}?token={new_token}|{urllib.parse.quote(f'{base_url}/api', safe='')}|{uuid.uuid4()}|{self.user_id.id}|{self.user_id.partner_id.id}|{'editor' if self.env.user.has_group('odashboard.group_odashboard_editor') else 'viewer'}|{','.join(str(id) for id in self.env.companies.ids)}"
        self.write({
            "token": new_token,
            "connection_url": new_connection_url,
            "last_authentication_date": datetime.now(),
            "allowed_company_ids": self.env.companies.ids
        })
