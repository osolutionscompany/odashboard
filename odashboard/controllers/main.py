from odoo import http
from odoo.http import request
from werkzeug.exceptions import NotFound
import requests


class Main(http.Controller):

    @http.route('/dashboard/public/<string:page_id>/<string:access_token>', type='http', auth='public', website=True)
    def dashboard_public_page(self, page_id, access_token, **kwargs):
        page = request.env['odash.config'].sudo().search([('is_page_config', '=', True), ('id', '=', page_id)], limit=1)
        if not page or page.access_token != access_token or not page.allow_public_access:
            raise NotFound()
        public_user = request.env.ref('base.public_user')
        connection_url = request.env['odash.dashboard'].sudo().get_dashboard_for_user(public_user.id, page.id)
        return request.render('odashboard.dashboard_public_view', {
            'connection_url': connection_url,
        })

    @http.route('/dashboard/public/<string:page_id>/<string:access_token>/pdf', type='http', auth='public', website=True)
    def dashboard_public_page_pdf(self, page_id, access_token, **kwargs):
        page = request.env['odash.config'].sudo().search([('is_page_config', '=', True), ('id', '=', page_id)], limit=1)
        if not page or page.secret_access_token != access_token:
            raise NotFound()
        public_user = request.env.ref('base.public_user')
        connection_url = request.env['odash.dashboard'].sudo().get_dashboard_for_user(public_user.id, page.id)

        pdf_url = request.env['ir.config_parameter'].sudo().get_param('odashboard.pdf.url', 'https://pdf.odashboard.app')
        payload = {"url": f"{connection_url}&is_pdf=true"}

        try:
            resp = requests.post(f"{pdf_url}/render", json=payload, timeout=120)
        except requests.RequestException as e:
            return request.make_response(
                '{"error":"PDF service unreachable","detail":"%s"}' % str(e).replace('"', '\\"'),
                headers=[('Content-Type', 'application/json')],
            )

        if resp.status_code != 200 or resp.headers.get('Content-Type', '').startswith('application/json'):
            return request.make_response(
                resp.content or b'{"error":"PDF service returned an error"}',
                headers=[('Content-Type', resp.headers.get('Content-Type', 'application/json'))],
            )

            # Success: return the PDF inline
        return request.make_response(
            resp.content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'inline; filename="odashboard.pdf"'),
            ],
        )
