from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class OdashCategory(models.Model):
    _name = 'odash.category'
    _description = 'Dashboard Page Category'
    _order = 'sequence, name'
    _rec_name = 'name'

    name = fields.Char(
        string='Category Name',
        required=True,
        translate=True,
        help="Name of the category (e.g., Sales, Support, Finance)"
    )
    
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help="Determines the display order of categories"
    )
    
    description = fields.Text(
        string='Description',
        translate=True,
        help="Brief description of what this category contains"
    )
    
    active = fields.Boolean(
        string='Active',
        default=True,
        help="If unchecked, this category will be hidden"
    )
    
    page_ids = fields.One2many(
        'odash.config',
        'category_id',
        string='Pages',
        domain=[('is_page_config', '=', True)],
        help="Dashboard pages in this category"
    )
    
    page_count = fields.Integer(
        string='Number of Pages',
        compute='_compute_page_count',
        store=True,
        help="Total number of pages in this category"
    )
    
    icon = fields.Char(
        string='Icon',
        help="Font Awesome icon class (e.g., fa-chart-line, fa-users)"
    )
    
    @api.depends('page_ids')
    def _compute_page_count(self):
        for record in self:
            record.page_count = len(record.page_ids)
    
    @api.constrains('name')
    def _check_unique_name(self):
        for record in self:
            if record.name:
                duplicate = self.search([
                    ('name', '=ilike', record.name),
                    ('id', '!=', record.id)
                ], limit=1)
                if duplicate:
                    raise ValidationError(
                        _('A category with the name "%s" already exists. Category names must be unique.') % record.name
                    )
    
    def name_get(self):
        """Display category name with page count"""
        result = []
        for record in self:
            name = record.name
            if record.page_count:
                name = f"{name} ({record.page_count})"
            result.append((record.id, name))
        return result
