import json
import base64
from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError


class OdashConfigImportWizard(models.TransientModel):
    _name = 'odash.config.import.wizard'
    _description = 'Import Dashboard Configurations Wizard'

    import_file = fields.Binary(string='Configuration File', required=True,
                                help="Select the JSON file exported from odashboard")
    filename = fields.Char(string='Filename')
    import_mode = fields.Selection([
        ('merge', 'Merge with Existing Configurations'),
        ('replace', 'Replace All Configurations'),
        ('skip_existing', 'Skip Existing Configurations')
    ], string='Import Mode', default='merge', required=True)

    # Preview fields
    preview_data = fields.Text(string='Preview', readonly=True)
    show_preview = fields.Boolean(string='Show Preview', default=False)

    @api.onchange('import_file')
    def _onchange_import_file(self):
        """Preview the import file content"""
        if self.import_file:
            try:
                file_content = base64.b64decode(self.import_file).decode('utf-8')
                import_data = json.loads(file_content)

                # Validate file structure
                if 'configs' not in import_data:
                    raise ValidationError(_("Invalid file format. Missing 'configs' key."))

                # Create preview
                preview_lines = [
                    f"Export Date: {import_data.get('export_date', 'Unknown')}",
                    f"Odoo Version: {import_data.get('odoo_version', 'Unknown')}",
                    f"Odashboard Version: {import_data.get('odashboard_version', 'Unknown')}",
                    f"Total Configurations: {len(import_data['configs'])}",
                ]

                # Show categories if present
                if import_data.get('categories'):
                    preview_lines.append(f"Categories: {len(import_data['categories'])}")
                    preview_lines.append("")
                    preview_lines.append("Categories to import:")
                    for category in import_data['categories'][:5]:  # Show first 5
                        preview_lines.append(f"- {category.get('name', 'Unnamed')}")
                    if len(import_data['categories']) > 5:
                        preview_lines.append(f"... and {len(import_data['categories']) - 5} more")
                    preview_lines.append("")

                preview_lines.append("")
                preview_lines.append("Configurations to import:")

                for config in import_data['configs'][:10]:  # Show first 10
                    config_type = "Page" if config.get('is_page_config') else "Component"
                    category_info = f" [{config.get('category_name')}]" if config.get('category_name') else ""
                    preview_lines.append(f"- {config.get('name', 'Unnamed')} ({config_type}){category_info}")

                if len(import_data['configs']) > 10:
                    preview_lines.append(f"... and {len(import_data['configs']) - 10} more")

                self.preview_data = "\n".join(preview_lines)
                self.show_preview = True

            except json.JSONDecodeError:
                raise ValidationError(_("Invalid JSON file format."))
            except Exception as e:
                raise ValidationError(_("Error reading file: %s") % str(e))
        else:
            self.preview_data = ""
            self.show_preview = False

    def _import_category(self, category_data):
        """Import or update a single category"""
        category_name = category_data.get('name')
        if not category_name:
            return None

        # Search for existing category
        existing_category = self.env['odash.category'].search([('name', '=', category_name)], limit=1)

        # Prepare security groups
        security_group_ids = []
        if category_data.get('security_groups'):
            for group_name in category_data['security_groups']:
                group = self.env['odash.security.group'].search([('name', '=', group_name)], limit=1)
                if group:
                    security_group_ids.append(group.id)

        # Prepare users
        user_ids = []
        if category_data.get('users'):
            for user_login in category_data['users']:
                user = self.env['res.users'].search([('login', '=', user_login)], limit=1)
                if user:
                    user_ids.append(user.id)

        # Prepare category values
        category_values = {
            'name': category_name,
            'sequence': category_data.get('sequence', 10),
            'description': category_data.get('description', ''),
            'active': category_data.get('active', True),
            'icon': category_data.get('icon', ''),
            'security_group_ids': [(6, 0, security_group_ids)],
            'user_ids': [(6, 0, user_ids)],
        }

        if existing_category:
            # Update existing category (always merge for categories)
            existing_category.write(category_values)
            return existing_category
        else:
            # Create new category
            return self.env['odash.category'].create(category_values)

    def action_import(self):
        """Execute the import process"""
        if not self.import_file:
            raise UserError(_("Please select a file to import."))

        try:
            # Decode and parse the file
            file_content = base64.b64decode(self.import_file).decode('utf-8')
            import_data = json.loads(file_content)

            if 'configs' not in import_data:
                raise ValidationError(_("Invalid file format. Missing 'configs' key."))

            # Handle replace mode first
            if self.import_mode == 'replace':
                # Delete all existing configurations
                existing_configs = self.env['odash.config'].search([])
                existing_configs.unlink()
                existing_configs = self.env['odash.config']  # Empty recordset
            else:
                # Get existing configurations for merge/skip modes
                existing_configs = self.env['odash.config'].search([])

            # Import categories first (if present in export)
            category_map = {}  # Maps category names to category records
            categories_imported = 0
            if import_data.get('categories'):
                for category_data in import_data['categories']:
                    category = self._import_category(category_data)
                    if category:
                        category_map[category_data.get('name')] = category
                        categories_imported += 1

            imported_count = 0
            skipped_count = 0

            for config_data in import_data['configs']:
                # Check if configuration already exists (only for non-replace modes)
                existing_config = self.env['odash.config']
                if self.import_mode != 'replace':
                    existing_config = existing_configs.filtered(
                        lambda c: c.config_id == config_data.get('config_id') and
                                  c.is_page_config == config_data.get('is_page_config', False)
                    )

                if existing_config and self.import_mode == 'skip_existing':
                    skipped_count += 1
                    continue

                # Prepare security groups
                security_group_ids = []
                if config_data.get('security_groups'):
                    for group_name in config_data['security_groups']:
                        group = self.env['odash.security.group'].search([('name', '=', group_name)], limit=1)
                        if group:
                            security_group_ids.append(group.id)

                # Prepare users
                user_ids = []
                if config_data.get('users'):
                    for user_login in config_data['users']:
                        user = self.env['res.users'].search([('login', '=', user_login)], limit=1)
                        if user:
                            user_ids.append(user.id)

                # Get category if specified
                category_id = False
                if config_data.get('category_name'):
                    category_name = config_data['category_name']
                    # First check if we imported it in this session
                    if category_name in category_map:
                        category_id = category_map[category_name].id
                    else:
                        # Otherwise, search for existing category
                        category = self.env['odash.category'].search([('name', '=', category_name)], limit=1)
                        if category:
                            category_id = category.id
                        else:
                            # Create a basic category if it doesn't exist
                            category = self.env['odash.category'].create({'name': category_name})
                            category_map[category_name] = category
                            category_id = category.id

                # Prepare configuration values
                config_values = {
                    'name': config_data.get('name', _('Unnamed')),
                    'sequence': config_data.get('sequence', 1),
                    'is_page_config': config_data.get('is_page_config', False),
                    'config_id': config_data.get('config_id'),
                    'config': config_data.get('config', {}),
                    'category_id': category_id,
                    'security_group_ids': [(6, 0, security_group_ids)],
                    'user_ids': [(6, 0, user_ids)],
                }

                if existing_config and self.import_mode == 'merge':
                    # Update existing configuration
                    existing_config.write(config_values)
                else:
                    # Create new configuration
                    self.env['odash.config'].create(config_values)

                imported_count += 1

            # Show success message
            message = _("Import completed successfully!\n")
            if categories_imported > 0:
                message += _("Categories: %s\n") % categories_imported
            message += _("Configurations: %s\n") % imported_count
            if skipped_count > 0:
                message += _("Skipped: %s") % skipped_count

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Import Successful'),
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}
                }
            }

        except json.JSONDecodeError:
            raise UserError(_("Invalid JSON file format."))
        except Exception as e:
            raise UserError(_("Import failed: %s") % str(e))
