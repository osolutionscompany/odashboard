import json
import logging
from datetime import datetime, date

from odoo import http
from odoo.http import request, Response

from .api_helper import ApiHelper

_logger = logging.getLogger(__name__)


class OdashboardJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super(OdashboardJSONEncoder, self).default(obj)


class OdashboardAPI(http.Controller):

    @http.route(['/api/odash/access'], type='http', auth='api_key_dashboard', csrf=False, methods=['GET'], cors="*")
    def get_access(self):
        token = request.env['ir.config_parameter'].sudo().get_param('odashboard.api.token')
        return ApiHelper.json_valid_response(token, 200)

    @http.route(['/api/osolution/refresh-token/<string:uuid>/<string:key>'], type='http', auth='none', csrf=False,
                methods=['GET'], cors="*")
    def refresh_token(self, uuid, key):
        ConfigParameter = request.env['ir.config_parameter'].sudo()

        uuid_param = ConfigParameter.get_param('odashboard.uuid')
        key_param = ConfigParameter.get_param('odashboard.key')

        if uuid_param == uuid and key_param == key:
            request.env["odash.dashboard"].sudo().update_auth_token()
        return ApiHelper.json_valid_response("ok", 200)

    @http.route(['/api/get/models'], type='http', auth='api_key_dashboard', csrf=False, methods=['GET'], cors="*")
    def get_models(self):
        """
        Return a list of models relevant for analytics, automatically filtering out technical models

        :return: JSON response with list of analytically relevant models
        """
        engine = request.env['odash.engine'].sudo()._get_single_record()

        # Use the engine to get the models
        result = engine.execute_engine_code('get_models', request.env)

        if result.get('success'):
            return ApiHelper.json_valid_response(result.get('data', []), 200)
        else:
            return ApiHelper.json_valid_response({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }, 500)

    @http.route(['/api/get/model_fields/<string:model_name>'], type='http', auth='api_key_dashboard', csrf=False,
                methods=['GET'], cors="*")
    def get_model_fields(self, model_name, **kw):
        """
        Retrieve information about the fields of a specific Odoo model.

        :param model_name: Name of the Odoo model (example: 'sale.order')
        :return: JSON with information about the model's fields
        """
        engine = request.env['odash.engine'].sudo()._get_single_record()

        # Use the engine to get the model fields
        result = engine.execute_engine_code('get_model_fields', model_name, request.env)

        return self._build_response(result.get('data', {}), 200)

    @http.route(['/api/get/model_records/<string:model_name>'], type='http', auth='none', csrf=False,
                methods=['GET'], cors="*")
    def get_model_records(self, model_name, **kw):
        """
        Retrieve information about the fields of a specific Odoo model.

        :param model_name: Name of the Odoo model (example: 'sale.order')
        :return: JSON with information about the model's fields
        """
        engine = request.env['odash.engine'].sudo()._get_single_record()

        # Use the engine to get the model fields
        result = engine.execute_engine_code('get_model_records', model_name, kw, request.env)

        return self._build_response(result.get('data', {}), 200)

    @http.route(['/api/get/model_search/<string:model_name>'], type='http', auth='api_key_dashboard', csrf=False,
                methods=['GET'], cors="*")
    def get_model_search(self, model_name, **kw):
        engine = request.env['odash.engine'].sudo()._get_single_record()

        # Use the engine to get the model fields
        result = engine.execute_engine_code('get_model_search', model_name, kw, request)

        return self._build_response(result.get('data', {}), 200)

    @http.route('/api/get/dashboard', type='http', auth='api_key_dashboard', csrf=False, methods=['POST'], cors='*')
    def get_dashboard_data(self):
        """
        Main endpoint to get dashboard visualization data.
        Accepts JSON configurations for blocks, graphs, and tables.
        Uses the dynamic dashboard engine for processing.
        """
        with request.env.cr.savepoint():
            engine = request.env['odash.engine'].sudo()._get_single_record()

            # Check update if there is no code
            if not engine.code:
                engine.check_for_updates()

            request_data = json.loads(request.httprequest.data.decode('utf-8'))

            # Use the engine to process the dashboard request
            # The engine now handles all validation and processing
            results = engine.execute_engine_code('process_dashboard_request',
                                                 request_data, request.env)

            return self._build_response([results], 200)

    def _build_response(self, data, status=200):
        """Build a consistent JSON response with the given data and status."""
        headers = {'Content-Type': 'application/json'}
        return Response(json.dumps(data, cls=OdashboardJSONEncoder),
                        status=status,
                        headers=headers)
