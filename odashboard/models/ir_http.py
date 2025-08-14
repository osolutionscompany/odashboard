from odoo import models, api
from odoo.http import request
from werkzeug.exceptions import Unauthorized


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_api_key_dashboard(cls):
        if request.httprequest.method == "OPTIONS":
            return

        api_key = request.httprequest.headers.get("Authorization")
        if not api_key or len(api_key) < 8:
            raise Unauthorized("Authorization header with API key missing")
        api_key = api_key[7:]

        dashboard_id = request.env['odash.dashboard'].sudo().search([('token', '=', api_key)], limit=1)

        if not dashboard_id:
            raise Unauthorized("Invalid token")

        request.update_env(user=dashboard_id.user_id, context=dict(request.context, page_id=dashboard_id.page_id, dashboard_id=dashboard_id))
