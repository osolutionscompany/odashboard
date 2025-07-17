import urllib.parse
import string
import random
import uuid
import requests

from odoo import models, fields, api


def generate_random_string(n):
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choice(characters) for _ in range(n))
    return random_string


class Dashboard(models.Model):
    _name = "odash.dashboard"
    _description = "Dashboard"

    name = fields.Char(default='Odashboard')

    user_id = fields.Many2one("res.users", string="User")

    connection_url = fields.Char(string="URL")
    token = fields.Char(string="Token")
    config = fields.Json(string="Config")

    @api.model
    def update_auth_token(self):
        uuid_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')
        key_param = self.env['ir.config_parameter'].sudo().get_param('odashboard.key')
        api_endpoint = self.env['ir.config_parameter'].sudo().get_param('odashboard.api.endpoint')
        token = requests.get(f"{api_endpoint}/api/odash/access/{uuid_param}/{key_param}")
        if token.status_code == 200:
            token = token.json()
            self.env['ir.config_parameter'].sudo().set_param('odashboard.api.token', token)

    def get_dashboard_for_user(self):
        user_id = self.env.user.id
        dashboard_id = self.search([('user_id', '=', user_id)], limit=1)

        if not dashboard_id:
            dashboard_id = self.create({
                'user_id': user_id,
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

    def _refresh(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        new_token = generate_random_string(64) if not self.token else self.token
        new_connection_url = f"https://app.odashboard.app?token={new_token}|{urllib.parse.quote(f'{base_url}/api', safe='')}|{uuid.uuid4()}|{self.env.user.id}"
        self.write({
            "token": new_token,
            "connection_url": new_connection_url,
        })
