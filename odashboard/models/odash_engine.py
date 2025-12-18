import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

from . import engine_logic

_logger = logging.getLogger(__name__)


class DashboardEngine(models.Model):
    """
    This model manages the Odashboard visualization engine.
    The engine logic is now embedded directly in engine_logic.py for better
    reliability, debugging, and maintenance.
    Singleton pattern enforced via create() method override.
    """
    _name = 'odash.engine'
    _description = 'Dashboard Engine'
    _order = 'create_date desc'

    name = fields.Char(string='Name', default='Dashboard Engine', readonly=True)
    version = fields.Char(string='Version', default='2.0.0', readonly=True,
                         help="Engine version - now embedded in the module")

    @api.model
    def _get_single_record(self):
        """Get or create the single engine record.

        Returns the singleton engine record, creating it if it doesn't exist.
        """
        engine = self.search([], limit=1)
        if engine:
            return engine

        # Create the singleton record
        return self.create({
            'name': 'Dashboard Engine',
            'version': '1.2.0',
        })


    def _execute_unified_request(self, action, parameters, env, request=None):
        """
        Unified request dispatcher that routes requests to engine_logic methods.

        Args:
            action (str): The action to perform (method name in engine_logic)
            parameters (dict): Action-specific parameters
            env: Odoo environment
            request: HTTP request object (optional, needed for some actions)

        Returns:
            dict: Standardized response with 'success', 'data', and 'error' keys
        """
        self.ensure_one()

        try:
            # Map actions to engine_logic functions
            action_map = {
                'get_user_context': lambda: engine_logic.get_user_context(env),
                'get_models': lambda: engine_logic.get_models(env),
                'get_model_fields': lambda: engine_logic.get_model_fields(
                    parameters.get('model_name'), env
                ),
                'get_model_search': lambda: engine_logic.get_model_search(
                    parameters.get('model_name'), parameters, request
                ),
                'process_dashboard_request': lambda: engine_logic.process_dashboard_request(
                    parameters.get('request_data', parameters), env
                ),
            }

            if action not in action_map:
                return {
                    'success': False,
                    'error': _("Unsupported action: %s") % action
                }

            # Validate required parameters
            validation_error = self._validate_parameters(action, parameters)
            if validation_error:
                return validation_error

            # Execute the action
            result = action_map[action]()

            # Standardize the response format
            return self._standardize_response(result)

        except Exception as e:
            _logger.exception("Error in _execute_unified_request: %s", e)
            return {
                'success': False,
                'error': str(e)
            }

    def _validate_parameters(self, action, parameters):
        """Validate required parameters for each action."""
        required_params = {
            'get_model_fields': ['model_name'],
            'get_model_search': ['model_name'],
            'process_dashboard_request': ['request_data'],
        }

        for param in required_params.get(action, []):
            if not parameters.get(param):
                return {
                    'success': False,
                    'error': _("Missing required parameter: %s") % param
                }

        return None

    def _standardize_response(self, result):
        """Standardize engine response format."""
        if isinstance(result, dict):
            if 'success' in result:
                return result
            elif 'error' in result:
                return {
                    'success': False,
                    'error': result['error']
                }
            elif 'data' in result:
                return {
                    'success': True,
                    'data': result['data']
                }
            else:
                return {
                    'success': True,
                    'data': result
                }
        else:
            return {
                'success': True,
                'data': result
            }

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to enforce singleton pattern."""
        existing = self.search([], limit=1)
        if existing:
            raise ValidationError(_(
                'Cannot create Dashboard Engine record. '
                'Only one engine record is allowed and one already exists (ID: %s). '
                'Use _get_single_record() method instead.'
            ) % existing.id)
        if len(vals_list) > 1:
            raise ValidationError(_("Only one Dashboard Engine record can be created at a time"))
        return super(DashboardEngine, self).create(vals_list)
