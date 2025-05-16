from odoo import models, fields, api, _
import logging
import requests
import json
import base64
import ast
import os
from datetime import datetime

_logger = logging.getLogger(__name__)

class DashboardEngine(models.Model):
    """
    This model manages the Odashboard visualization engine code and its updates.
    It can automatically check for updates on GitHub and apply them when available.
    """
    _name = 'odash.engine'
    _description = 'Dashboard Engine'

    name = fields.Char(string='Name', default='Dashboard Engine', readonly=True)
    version = fields.Char(string='Version', default='1.0.0', readonly=True)
    code = fields.Text(string='Engine Code', readonly=True, 
                      help="Python code for the dashboard visualization engine")
    previous_code = fields.Text(string='Previous Engine Code', readonly=True,
                               help="Previous version of the engine code (for fallback)")
    install_date = fields.Datetime(string='Install Date', readonly=True)
    last_update_date = fields.Datetime(string='Last Update Date', readonly=True)
    last_check_date = fields.Datetime(string='Last Check Date', readonly=True)
    auto_update = fields.Boolean(string='Auto Update', default=True,
                               help="Check for updates automatically")
    update_log = fields.Text(string='Update Log', readonly=True,
                            help="Log of update attempts and results")

    @api.model
    def _get_github_base_url(self):
        """Get the base URL for GitHub repository."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'odashboard.github_base_url', 
            'https://raw.githubusercontent.com/Notdoo/odashboard.engine/main/'
        )

    @api.model
    def _get_local_engine_path(self):
        """Get the local path for engine.py file.
        This is used during development to load engine code directly from the local filesystem.
        """
        return self.env['ir.config_parameter'].sudo().get_param(
            'odashboard.local_engine_path',
            '/Users/julienmasson/Projects/Odoo/perso/osolutions/odashboard_engine/versions/1.0.0/engine.py'
        )

    @api.model
    def _get_versions_url(self):
        """Get the URL for versions.json file."""
        base_url = self._get_github_base_url()
        return f"{base_url}versions.json"

    @api.model
    def _get_single_record(self):
        """Get or create the single engine record."""
        engine = self.search([], limit=1)
        if not engine:
            # Initialize with embedded code if no record exists
            from odoo.modules.module import get_module_resource
            code_path = get_module_resource('odashboard', 'static', 'src', 'engine', 'engine.py')
            code = ''
            if code_path:
                with open(code_path, 'r') as f:
                    code = f.read()
            
            engine = self.create({
                'name': 'Dashboard Engine',
                'version': '1.0.0',
                'code': code,
                'previous_code': code,
                'install_date': fields.Datetime.now(),
                'last_update_date': fields.Datetime.now(),
                'last_check_date': fields.Datetime.now(),
            })
        return engine

    def _add_to_log(self, message):
        """Add a timestamped message to the update log."""
        timestamp = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_log = self.update_log or ''
        self.update_log = f"{current_log}\n[{timestamp}] {message}" if current_log else f"[{timestamp}] {message}"

    def check_for_updates(self):
        """
        Check GitHub for engine updates.
        Returns True if an update is available and successfully applied.
        """
        self.ensure_one()
        engine = self
        
        try:
            # Update last check date
            engine.write({'last_check_date': fields.Datetime.now()})
            
            # Fetch versions.json from GitHub
            versions_url = self._get_versions_url()
            _logger.info(f"Checking for updates at: {versions_url}")
            
            response = requests.get(versions_url, timeout=10)
            if response.status_code != 200:
                message = f"Failed to fetch versions.json: HTTP {response.status_code}"
                _logger.error(message)
                self._add_to_log(message)
                return False
            
            versions_data = response.json()
            latest_version = versions_data.get('latest')
            
            if not latest_version:
                message = "No 'latest' version found in versions.json"
                _logger.error(message)
                self._add_to_log(message)
                return False
            
            # Compare versions
            current_version = engine.version
            _logger.info(f"Current version: {current_version}, Latest version: {latest_version}")
            
            if current_version == latest_version and engine.code:
                message = f"Already at the latest version ({latest_version})"
                _logger.info(message)
                self._add_to_log(message)
                return False
            
            # Get version details
            version_info = versions_data.get('versions', {}).get(latest_version)
            if not version_info or not version_info.get('path'):
                message = f"No path information for version {latest_version}"
                _logger.error(message)
                self._add_to_log(message)
                return False
            
            # Download the update
            code_path = version_info.get('path')
            code_url = f"{self._get_github_base_url()}{code_path}"
            
            return self._download_update(code_url, latest_version, version_info)
            
        except Exception as e:
            message = f"Error checking for updates: {str(e)}"
            _logger.exception(message)
            self._add_to_log(message)
            return False

    def _download_update(self, code_url, new_version, version_info):
        """
        Download and apply an engine update.
        Returns True if successful, False otherwise.
        """
        self.ensure_one()
        engine = self
        
        try:
            _logger.info(f"Downloading update from: {code_url}")
            response = requests.get(code_url, timeout=15)
            
            if response.status_code != 200:
                message = f"Failed to download update: HTTP {response.status_code}"
                _logger.error(message)
                self._add_to_log(message)
                return False
            
            new_code = response.text
            
            # Validate Python syntax
            try:
                ast.parse(new_code)
            except SyntaxError as e:
                message = f"Invalid Python syntax in downloaded code: {str(e)}"
                _logger.error(message)
                self._add_to_log(message)
                return False
            
            # Save previous code for fallback
            current_code = engine.code
            
            # Update the engine
            engine.write({
                'previous_code': current_code,
                'code': new_code,
                'version': new_version,
                'last_update_date': fields.Datetime.now(),
            })
            
            message = f"Successfully updated to version {new_version}: {version_info.get('description', 'No description')}"
            _logger.info(message)
            self._add_to_log(message)
            return True
            
        except Exception as e:
            message = f"Error downloading update: {str(e)}"
            _logger.exception(message)
            self._add_to_log(message)
            return False

    def execute_engine_code(self, method_name, *args, **kwargs):
        """
        Execute a method from the engine code.
        If execution fails, fall back to the previous version.
        In development mode, it will try to load code from the local file system first.
        """
        self.ensure_one()
        engine = self

        code = engine.code
        if not code:
            _logger.error("No engine code available")
            return {'error': 'No engine code available'}
        
        # Try to execute the current code
        try:
            # Create a namespace that will be shared by all functions
            # Using the same dictionary for globals and locals ensures all functions
            # share the same namespace and can reference each other
            shared_namespace = {}
            
            # Execute the code in the shared namespace
            exec(code, shared_namespace, shared_namespace)
            
            # Check if the method exists in the namespace
            if method_name in shared_namespace:
                func = shared_namespace[method_name]
                result = func(*args, **kwargs)
                return result
            else:
                _logger.error(f"Method '{method_name}' not found in engine code")
                return {'error': f"Method '{method_name}' not found in engine code"}
                
        except Exception as e:
            _logger.exception(f"Error executing '{method_name}': {str(e)}")
            
            # Try with previous code as a fallback
            if engine.previous_code and engine.previous_code != code:
                try:
                    _logger.info(f"Attempting fallback execution of '{method_name}'")
                    
                    # Create a shared namespace for fallback
                    fallback_namespace = {}
                    
                    # Execute the previous code with shared namespace
                    exec(engine.previous_code, fallback_namespace, fallback_namespace)
                    
                    # Check if the method exists in the fallback namespace
                    if method_name in fallback_namespace:
                        func = fallback_namespace[method_name]
                        result = func(*args, **kwargs)
                    else:
                        return {'error': f"Method '{method_name}' not found in fallback code"}
                
                    # Log the fallback
                    self._add_to_log(f"Executed '{method_name}' using fallback code due to error: {str(e)}")
                    
                    return result
                    
                except Exception as fallback_error:
                    _logger.exception(f"Error executing fallback for '{method_name}': {str(fallback_error)}")
                    return {'error': f"Error in engine execution: {str(e)}. Fallback also failed: {str(fallback_error)}"}
            
            return {'error': f"Error in engine execution: {str(e)}"}

    @api.model
    def auto_check_updates(self):
        """
        Automatically check for updates if enabled.
        This can be called by a scheduled action.
        """
        engine = self._get_single_record()
        if engine.auto_update:
            _logger.info("Automatically checking for engine updates")
            engine.check_for_updates()
        return True
