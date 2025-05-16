import json
import logging
from datetime import datetime, date

from odoo import http, fields
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
    def get_access(self, **kw):
        token = request.env['ir.config_parameter'].sudo().get_param('odashboard.api.token')
        return ApiHelper.json_valid_response(token, 200)

    @http.route(['/api/osolution/refresh-token/<string:uuid>/<string:key>'], type='http', auth='none', csrf=False,
                methods=['GET'], cors="*")
    def refresh_token(self, uuid, key, **kw):
        uuid_param = request.env['ir.config_parameter'].sudo().get_param('odashboard.uuid')
        key_param = request.env['ir.config_parameter'].sudo().get_param('odashboard.key')

        if uuid_param == uuid and key_param == key:
            request.env["odash.dashboard"].sudo().update_auth_token()
        return ApiHelper.json_valid_response("ok", 200)

    @http.route(['/api/get/models'], type='http', auth='api_key_dashboard', csrf=False, methods=['GET'], cors="*")
    def get_models(self, **kw):
        """
        Return a list of models relevant for analytics, automatically filtering out technical models

        :return: JSON response with list of analytically relevant models
        """
        try:
            _logger.info("API call: Fetching list of analytically relevant models")

            # Create domain to filter models directly in the search
            # 1. Must be non-transient
            domain = [('transient', '=', False)]

            # 2. Exclude technical models using NOT LIKE conditions
            technical_prefixes = ['ir.', 'base.', 'bus.', 'base_import.',
                                'web.', 'mail.', 'auth.', 'report.',
                                'resource.', 'wizard.']
            for prefix in technical_prefixes:
                domain.append(('model', 'not like', f'{prefix}%'))

            # Models starting with underscore
            domain.append(('model', 'not like', '\\_%'))

            # Execute the optimized search
            model_obj = request.env['ir.model'].sudo()
            models = model_obj.search(domain)

            _logger.info("Found %s analytical models", len(models))

            # Format the response with the already filtered models
            model_list = [{
                'name': model.name,
                'model': model.model,
            } for model in models]

            return ApiHelper.json_valid_response(model_list, 200)

        except Exception as e:
            _logger.error("Error in API get_models: %s", str(e))
            error_response = {
                'success': False,
                'error': str(e)
            }
            response = Response(
                json.dumps(error_response, cls=OdashboardJSONEncoder),
                content_type='application/json',
                status=500
            )
            return response
            
    @http.route(['/api/get/model_fields/<string:model_name>'], type='http', auth='api_key_dashboard', csrf=False,
                methods=['GET'], cors="*")
    def get_model_fields(self, model_name, **kw):
        """
        Retrieve information about the fields of a specific Odoo model.

        :param model_name: Name of the Odoo model (example: 'sale.order')
        :return: JSON with information about the model's fields
        """
        try:
            _logger.info("API call: Fetching fields info for model: %s", model_name)

            # Check if the model exists
            if model_name not in request.env:
                return self._build_response({'success': False, 'error': f"Model '{model_name}' not found"}, status=404)

            # Get field information
            model_obj = request.env[model_name].sudo()
            
            # Get fields info
            fields_info = {}
            for name, field in model_obj._fields.items():
                # Skip binary fields and function fields without a store
                if field.type == 'binary' or (field.compute and not field.store):
                    continue
                    
                # Get field properties
                field_info = {
                    'type': field.type,
                    'string': field.string,
                    'relation': field.comodel_name if hasattr(field, 'comodel_name') else None,
                    'store': field.store if hasattr(field, 'store') else True,
                    'required': field.required,
                    'readonly': field.readonly,
                }
                
                fields_info[name] = field_info

            return self._build_response({'success': True, 'data': fields_info}, 200)

        except Exception as e:
            _logger.error("Error in API get_model_fields: %s", str(e))
            return self._build_response({'success': False, 'error': str(e)}, status=500)

    @http.route('/api/get/dashboard', type='http', auth='none', csrf=False, methods=['POST'], cors='*')
    def get_dashboard_data(self):
        """Main endpoint to get dashboard visualization data.
        Accepts JSON configurations for blocks, graphs, and tables.
        Uses the dynamic dashboard engine for processing.
        """
        try:
            # Get the engine instance
            engine_model = request.env['odash.engine'].sudo()
            engine = engine_model._get_single_record()
            
            # Check for updates if enabled
            if engine.auto_update:
                # Only check once per day maximum
                last_check = engine.last_check_date
                now = fields.Datetime.now()
                if not last_check or (now - last_check).total_seconds() > 86400 or not engine.code:
                    _logger.info("Checking for engine updates")
                    engine.check_for_updates()
            
            # Parse JSON request data
            try:
                request_data = json.loads(request.httprequest.data.decode('utf-8'))
            except Exception as e:
                _logger.error("Error parsing JSON data: %s", e)
                return self._build_response({'error': 'Invalid JSON format'}, 400)
            
            # Use the engine to process the dashboard request
            # The engine now handles all validation and processing
            results = engine.execute_engine_code('process_dashboard_request', 
                                               request_data, request.env)
            
            return self._build_response(results)

        except Exception as e:
            _logger.exception("Unhandled error in get_dashboard_data:")
            return self._build_response({'error': str(e)}, 500)
            
    def _build_response(self, data, status=200):
        """Build a consistent JSON response with the given data and status."""
        headers = {'Content-Type': 'application/json'}
        return Response(json.dumps(data, cls=OdashboardJSONEncoder), 
                       status=status, 
                       headers=headers)

