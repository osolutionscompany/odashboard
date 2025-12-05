# -*- coding: utf-8 -*-

import uuid
import requests
import logging
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Post-init hook to create and synchronize demo key with O'Solutions system."""
    
    try:

        # Generate UUID4 for the demo key
        demo_key_uuid = str(uuid.uuid4())
        
        config_model = env['ir.config_parameter'].sudo()
        
        # Get database UUID
        odashboard_uuid = config_model.get_param('odashboard.uuid')
        if not odashboard_uuid:
            # Generate database UUID if it doesn't exist
            odashboard_uuid = str(uuid.uuid4())
            config_model.set_param('odashboard.uuid', odashboard_uuid)
        
        # Get instance URL
        base_url = config_model.get_param('web.base.url')
        if not base_url:
            _logger.error("Cannot determine instance URL, skipping demo key creation")
            return
        
        # Get O'Solutions API endpoint
        api_endpoint = config_model.get_param('odashboard.api.endpoint')

        # Get user email for trial expiration notification
        user_email = env.user.email or ''

        # Prepare data for API call
        api_data = {
            'key': demo_key_uuid,
            'uuid': odashboard_uuid,
            'url': base_url,
            'email': user_email,
        }
        
        # Make secure API call to create demo key
        try:
            response = requests.post(
                f"{api_endpoint}/api/get/odashboard_key",
                json=api_data,
                headers={'Content-Type': 'application/json'},
            )
            result = response.json().get('result', {})
            if result.get('error'):
                # TODO : In the hook it seems impossible to raise an User error......
                error_msg = result.get('error')
                _logger.error(f"Error creating demo key: {error_msg}")
                # Store error for later display in UI
                config_model.set_param('odashboard.init_error', error_msg)
                raise UserError(_("Failed to create demo key: %s") % error_msg)

            if result.get('valid'):
                sub_plan = result.get('odash_sub_plan', 'freemium')
                demo_key = result.get('license_key', demo_key_uuid)
                token = result.get('token', False)
                _logger.info(f"Demo key successfully created and synchronized: {demo_key}")
                    
                # Store demo key information in system parameters
                config_model.set_param('odashboard.key', demo_key)
                config_model.set_param('odashboard.plan', sub_plan)
                config_model.set_param('odashboard.key_synchronized', True)
                config_model.set_param('odashboard.api.token', token)
                config_model.set_param('odashboard.free_trial_end_date', result.get('free_end_date', False))
                config_model.set_param('odashboard.is_free_trial', result.get('is_free_plan', False))
            else:
                _logger.error(f"API call failed with status {response.status_code}: {response.text}")
                
        except requests.exceptions.RequestException as e:
            _logger.error(f"Network error while creating demo key: {str(e)}")
        except Exception as e:
            _logger.error(f"Unexpected error while creating demo key: {str(e)}")
            
    except Exception as e:
        _logger.error(f"Error in post_init_hook: {str(e)}")


def uninstall_hook(env):
    """Uninstall hook to clean up demo key data."""
    
    try:
        # Remove demo key parameters
        config_model.search([
            ('key', 'in', ['odashboard.key', 'odashboard.plan', 'odashboard.uuid', 'odashboard.api.token', 'odashboard.key_synchronized'])
        ]).unlink()
        
        _logger.info("Demo key parameters cleaned up during uninstall")
        
    except Exception as e:
        _logger.error(f"Error in uninstall_hook: {str(e)}")
