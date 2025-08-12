from odoo import http
from odoo.http import request
from werkzeug.exceptions import NotFound



class Main(http.Controller):

    @http.route('/dashboard/public/<string:page_id>/<string:access_token>', type='http', auth='public', website=True)
    def dashboard_public_page(self, page_id, access_token, **kwargs):
        page = request.env['odash.config'].sudo().search([('is_page_config', '=', True), ('id', '=', page_id)], limit=1)
        if not page or (page.access_token != access_token and page.secret_access_token != access_token):
            raise NotFound()
        if page.access_token == access_token and not page.allow_public_access:
            raise NotFound()
        public_user = request.env.ref('base.public_user')
        connection_url = request.env['odash.dashboard'].sudo().get_dashboard_for_user(public_user.id, page.id)
        return request.render('odashboard.dashboard_public_view', {
            'connection_url': connection_url,
        })
