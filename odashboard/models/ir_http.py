from odoo import models, api, _
from odoo.http import request
from odoo.tools import get_lang
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

        # Make sure the lang in the context always match lang installed in the Odoo System
        context_lang = request.context.get("lang") or "en_US"
        lang_code = cls.oso_get_lang(request.env, context_lang)
        request.session.context["lang"] = lang_code
        request.update_context(lang=lang_code)

        dashboard = request.env['odash.dashboard'].sudo().search([('token', '=', api_key)], limit=1)

        if not dashboard:
            raise Unauthorized(_("Invalid token"))

        request.update_env(
            user=dashboard.user_id,
            context=dict(request.context, page_id=dashboard.page_id, dashboard_id=dashboard)
        )

    @staticmethod
    def oso_get_lang(env, lang_code):
        """
        Retrieve the first lang object installed, by checking the parameter lang_code,
        the context and then the company. If no lang is installed from those variables,
        fallback on english or on the first lang installed in the system.

        :param env:
        :param str lang_code: the locale (i.e. en_US)
        :return LangData: the first lang found that is installed on the system.
        """
        lang_model = env['res.lang'].sudo()
        installed_langs = lang_model.get_installed()
        langs = [code for code, _ in installed_langs]
        lang = 'en_US' if 'en_US' in langs else langs[0]
        if lang_code and lang_code in langs:
            lang = lang_code
        elif (context_lang := env.context.get('lang')) in langs:
            lang = context_lang
        elif (company_lang := env.user.with_context(lang='en_US').company_id.partner_id.lang) in langs:
            lang = company_lang
        return lang_model._get_data(code=lang)