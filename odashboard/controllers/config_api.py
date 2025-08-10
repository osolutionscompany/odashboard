import uuid
import logging
from odoo import http
from odoo.http import request

from .api_helper import ApiHelper

_logger = logging.getLogger(__name__)

def check_access(config, user):

    if user.has_group('odashboard.group_odashboard_editor'):
        return True
    
    can_access = False

    if not config.is_page_config:
        return True
    
    if not config.security_group_ids and not config.user_ids:
        can_access = True
    else:
        if user in config.user_ids:
            can_access = True

        if not can_access:
            for group in config.security_group_ids:
                if user in group.user_ids:
                    can_access = True
                    break
    return can_access


class OdashConfigAPI(http.Controller):
    """
    Controller for CRUD operations on Odash Configuration.
    Provides two sets of endpoints:
    - /api/odash/pages/* for page configurations
    - /api/odash/data/* for data configurations
    """

    # ---- Page Configurations ----

    @http.route('/api/odash/pages', type='http', auth='api_key_dashboard', methods=['GET', 'POST'], csrf=False, cors="*")
    def pages_collection(self, **kw):
        """
        Handle page configurations collection
        GET: Get all page configurations
        POST: Create a new page configuration
        """

        method = request.httprequest.method
        odash_config = request.env['odash.config'].sudo()
        try:
            if method == 'GET':
                # Get all page configurations
                configs = odash_config.sudo().search([('is_page_config', '=', True)], order='sequence asc')
                result = []
                
                for config in configs:
                    if config.config and check_access(config, request.env.user):
                        result.append(config.config)
                        
                return ApiHelper.json_valid_response(result, 200)
            
            elif method == 'POST':
                # Create a new page configuration
                data = ApiHelper.load_json_data(request)
                
                # Generate UUID if id not provided
                if not data.get('id'):
                    data['id'] = str(uuid.uuid4())
                    
                # Create new config record
                config = odash_config.sudo().create({
                    'is_page_config': True,
                    'config_id': data.get('id'),
                    'config': data
                })

                odash_config.clean_unused_config()
                
                return ApiHelper.json_valid_response(config.config, 201)
                
        except Exception as e:
            operation = "getting" if method == 'GET' else "creating"
            _logger.error(f"Error {operation} page configs: {e}")
            return ApiHelper.json_error_response(e, 500)

    @http.route('/api/odash/pages/<string:config_id>', type='http', auth='api_key_dashboard', methods=['GET', 'PUT', 'DELETE'], csrf=False, cors="*")
    def page_resource(self, config_id, **kw):
        """
        Handle individual page configuration
        GET: Get a specific page configuration by ID
        PUT: Update an existing page configuration
        DELETE: Delete a page configuration
        """

        method = request.httprequest.method
        
        try:
            # Get the configuration record first (common for all methods)
            config = request.env['odash.config'].sudo().search([
                ('is_page_config', '=', True),
                ('config_id', '=', config_id)
            ], limit=1)
            
            if not config or not check_access(config, request.env.user):
                return ApiHelper.json_error_response("Page configuration not found", 404)
            
            if method == 'GET':
                # Return the configuration
                return ApiHelper.json_valid_response(config.config, 200)
                
            elif method == 'PUT':
                # Update the configuration
                data = ApiHelper.load_json_data(request)
                
                # Ensure ID remains the same
                updated_data = data.copy()
                updated_data['id'] = config_id
                
                # Update the configuration
                config.sudo().write({
                    'config': updated_data
                })
                
                return ApiHelper.json_valid_response(config.config, 200)
                
            elif method == 'DELETE':
                # Delete the configuration
                config.sudo().unlink()
                request.env['odash.config'].clean_unused_config()
                
                return ApiHelper.json_valid_response({"success": True}, 200)
                
        except Exception as e:
            operation = "getting" if method == 'GET' else ("updating" if method == 'PUT' else "deleting")
            _logger.error(f"Error {operation} page config: {e}")
            return ApiHelper.json_error_response(e, 500)

    # ---- Data Configurations ----

    @http.route('/api/odash/data', type='http', auth='api_key_dashboard', methods=['GET', 'POST'], csrf=False, cors="*")
    def data_collection(self, **kw):
        """
        Handle data configurations collection
        GET: Get all data configurations
        POST: Create a new data configuration
        """
        method = request.httprequest.method

        try:
            if method == 'GET':
                # Get all data configurations
                configs = request.env['odash.config'].sudo().search([('is_page_config', '=', False)])
                result = []
                
                for config in configs:
                    if config.config:
                        result.append(config.config)
                        
                return ApiHelper.json_valid_response(result, 200)
            
            elif method == 'POST':
                # Create a new data configuration
                data = ApiHelper.load_json_data(request)
                
                # Generate UUID if id not provided
                if not data.get('id'):
                    data['id'] = str(uuid.uuid4())
                    
                # Create new config record
                config = request.env['odash.config'].sudo().create({
                    'is_page_config': False,
                    'config_id': data.get('id'),
                    'config': data
                })
                
                return ApiHelper.json_valid_response(config.config, 201)
                
        except Exception as e:
            operation = "getting" if method == 'GET' else "creating"
            _logger.error(f"Error {operation} data configs: {e}")
            return ApiHelper.json_error_response(e, 500)

    @http.route('/api/odash/data/<string:config_id>', type='http', auth='api_key_dashboard', methods=['GET', 'PUT', 'DELETE'], csrf=False, cors="*")
    def data_resource(self, config_id, **kw):
        """
        Handle individual data configuration
        GET: Get a specific data configuration by ID
        PUT: Update an existing data configuration
        DELETE: Delete a data configuration
        """
        method = request.httprequest.method

        try:
            # Get the configuration record first (common for all methods)
            config = request.env['odash.config'].sudo().search([
                ('is_page_config', '=', False),
                ('config_id', '=', config_id)
            ], limit=1)
            
            if not config:
                return ApiHelper.json_error_response("Data configuration not found", 404)
            
            if method == 'GET':
                # Return the configuration
                return ApiHelper.json_valid_response(config.config, 200)
                
            elif method == 'PUT':
                # Update the configuration
                data = ApiHelper.load_json_data(request)
                
                # Ensure ID remains the same
                updated_data = data.copy()
                updated_data['id'] = config_id
                
                # Update the configuration
                config.sudo().write({
                    'config': updated_data
                })
                
                return ApiHelper.json_valid_response(config.config, 200)
                
            elif method == 'DELETE':
                # Delete the configuration
                config.sudo().unlink()
                
                return ApiHelper.json_valid_response({"success": True}, 200)
                
        except Exception as e:
            operation = "getting" if method == 'GET' else ("updating" if method == 'PUT' else "deleting")
            _logger.error(f"Error {operation} data config: {e}")
            return ApiHelper.json_error_response(e, 500)
