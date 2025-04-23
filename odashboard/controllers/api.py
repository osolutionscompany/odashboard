from .api_helper import ApiHelper

from odoo import http
from odoo.http import request, Response
import json
import logging
import random
from datetime import datetime, date

_logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects
class OdashboardJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super(OdashboardJSONEncoder, self).default(obj)

class OdashAPI(http.Controller):
    """
    Controller for Odashboard API endpoints
    """

    @http.route(['/api/odash/access'], type='http', auth='api_key_dashboard', csrf=False, methods=['GET'], cors="*")
    def get_access(self, **kw):
        token = request.env['ir.config_parameter'].sudo().get_param('odashboard.api.token')
        return ApiHelper.json_valid_response(token, 200)

    @http.route(['/api/osolution/refresh-token/<string:uuid>/<string:key>'], type='http', auth='none', csrf=False, methods=['GET'], cors="*")
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

            """
            # TODO : Améliorer le filtrage des modèles
                     # 3. Include only analytical models using OR conditions with LIKE
            analytical_domain = ['|'] * (14 - 1)  # 13 patterns minus 1
            analytical_domain += [
                ('model', 'like', 'sale.%'),
                ('model', 'like', 'account.%'),
                ('model', 'like', 'crm.%'),
                ('model', 'like', 'product.%'),
                ('model', 'like', 'purchase.%'),
                ('model', 'like', 'stock.%'),
                ('model', 'like', 'project.%'),
                ('model', 'like', 'hr.%'),
                ('model', 'like', 'pos.%'),
                ('model', 'like', 'mrp.%'),
                ('model', 'like', 'website_sale.%'),
                ('model', 'like', 'event.%'),
                ('model', 'like', 'marketing.%'),
                ('model', 'like', 'res.%'),
            ]
            
            # Combine all conditions
            domain = domain + analytical_domain
            
            """

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

    @http.route(['/api/get/dashboard'], type='http', auth='none', csrf=False, methods=['POST'], cors="*")
    def get_visualization_data(self, **kw):
        """
        Process the dashboard configuration and return data in the required format
        
        Accepts POST requests with JSON body containing one or multiple visualization configurations.
        
        Expected payload format for single configuration:
        {
            "id": string,
            "model": string,
            "type": "graph" | "table" | "block",
            "block_options": {
                "field": string,
                "aggregation": "count" | "sum" | "avg" | "min" | "max" | "count_distinct"
            },
            "data_source": {
                "domain": []
            }
        }
        
        Expected payload format for multiple configurations:
        [
            {
                "id": string,
                "model": string,
                "type": "graph" | "table" | "block",
                ...
            },
            {
                "id": string,
                "model": string, 
                "type": "graph" | "table" | "block",
                ...
            }
        ]
        
        :return: JSON response with the visualization data
        """
        try:
            params = self._extract_post_data(request, kw)

            _logger.info("API call: Params extracted: %s", type(params))

            # Check if params is a list (multiple configurations) or dict (single configuration)
            if isinstance(params, list):
                _logger.info("Processing multiple configurations")
                multiple_configs = params
            else:
                _logger.info("Processing single configuration")
                multiple_configs = [params]

            # Process each configuration
            response_data = []

            for config in multiple_configs:
                # Extract configuration fields
                config_id = config.get('id', '')
                model_name = config.get('model', '')
                visualization_type = config.get('type', '')

                _logger.info("API call: Processing dashboard data for config ID: %s, model: %s, type: %s",
                            config_id, model_name, visualization_type)

                # Parameter validation
                if not visualization_type:
                    continue  # Skip invalid configurations

                if not model_name:
                    continue  # Skip invalid configurations

                if not config_id:
                    continue  # Skip invalid configurations

                # Validate that the type is one of the allowed values
                allowed_types = ['graph', 'table', 'block']
                if visualization_type not in allowed_types:
                    continue  # Skip invalid configurations


                # Generate data based on visualization type
                visualization_data = None

                if visualization_type == 'graph':
                    # Get real data for a graph
                    graph_options = config.get('graph_options', {})
                    measures = graph_options.get('measures', [])

                    # Get domain, groupby and orderby from configuration
                    data_source = config.get('data_source', {})
                    domain = data_source.get('domain', [])
                    group_by = data_source.get('groupBy', {})
                    order_by = data_source.get('orderBy', {})

                    _logger.info("Generating graph data for model: %s, with measures: %s, groupby: %s",
                                model_name, measures, group_by)

                    try:
                        # Check if model exists
                        model_obj = request.env[model_name].sudo()

                        # If no measures specified, use count
                        if not measures:
                            measures = [{'field': 'id', 'aggregation': 'count', 'displayName': 'Count'}]

                        # Field to group by
                        groupby_field = group_by.get('field') if group_by else None
                        if not groupby_field:
                            # Default to grouping by creation month
                            groupby_field = 'create_date:month'

                        # Build the list of fields to aggregate for read_group
                        aggregation_fields = []
                        aggregation_names = {}

                        for measure in measures:
                            field_name = measure.get('field')
                            aggregation = measure.get('aggregation', 'sum')  # Default: sum
                            display_name = measure.get('displayName', field_name)

                            if field_name:
                                # Check if field exists
                                if field_name in model_obj._fields or field_name == 'id':
                                    # In read_group, we just pass the field name, not the aggregation type
                                    if field_name not in aggregation_fields and field_name != 'id':
                                        aggregation_fields.append(field_name)

                                    # Store the desired aggregation for each field
                                    aggregation_names[field_name] = {
                                        'display': display_name,
                                        'aggregation': aggregation
                                    }

                        # Prepare data based on chart type
                        chart_type = graph_options.get('chartType', 'bar')

                        # Set order if specified
                        orderby = None
                        if order_by and order_by.get('field'):
                            orderby_field = order_by.get('field')
                            direction = order_by.get('direction', 'asc')
                            orderby = f"{orderby_field} {direction}"

                        # Limit number of data points (for performance)
                        limit = 100

                        # Get grouped data
                        groups = model_obj.read_group(
                            domain=domain,
                            fields=aggregation_fields,
                            groupby=[groupby_field],
                            orderby=orderby,
                            limit=limit,
                            lazy=False
                        )

                        # Format data for response
                        data = []

                        for group in groups:
                            data_point = {}

                            # Extract the grouping key (format depends on field type)
                            # For date fields with interval, the key is in a special format
                            if ':' in groupby_field:  # Date with interval
                                base_field, interval = groupby_field.split(':')
                                group_value = group.get(groupby_field)
                                if group_value:
                                    data_point["key"] = group_value
                                else:
                                    data_point["key"] = "Undefined"
                            else:  # Standard fields
                                group_value = group.get(groupby_field)
                                if isinstance(group_value, tuple) and len(group_value) >= 2:
                                    # Many2one fields return (id, name)
                                    data_point["key"] = group_value[1]
                                else:
                                    # For other field types
                                    data_point["key"] = str(group_value) if group_value is not None else "Undefined"

                            # Add measures
                            for measure in measures:
                                field_name = measure.get('field')
                                aggregation = measure.get('aggregation', 'sum')

                                if field_name:
                                    measure_value = None

                                    # Key name depends on aggregation type
                                    if aggregation == 'count':
                                        # For count, Odoo automatically adds a special field
                                        if f"{groupby_field}_count" in group:
                                            measure_value = group.get(f"{groupby_field}_count", 0)
                                        else:
                                            measure_value = len(group.get('__domain', []))
                                    else:
                                        # For other aggregations, Odoo calculates automatically based on field type
                                        measure_value = group.get(field_name, 0)

                                    # Add value to data point
                                    data_point[field_name] = measure_value

                            # Ajout du domain spécifique au groupe
                            data_point["odash.domain"] = group.get("__domain", domain)
                            data.append(data_point)

                    except Exception as e:
                        _logger.error("Error generating graph data: %s", str(e))
                        # Return simulated data in case of error
                        data = []
                        current_year = datetime.now().year
                        for month in range(1, 7):  # January to June
                            data_point = {
                                "key": f"{current_year}-{month:02d}",  # Format: YYYY-MM
                            }
                            for measure in measures:
                                field_name = measure.get('field', '')
                                if field_name:
                                    data_point[field_name] = round(random.uniform(1000, 10000), 2)
                            data.append(data_point)

                    # Prepare response data
                    visualization_data = {
                        config_id: {
                            "data": data,
                        }
                    }

                elif visualization_type == 'table':
                    # Get real data for a table
                    table_options = config.get('table_options', {})
                    columns = table_options.get('columns', [])
                    page_size = table_options.get('pageSize', 10)

                    # Get domain, groupby and orderby from configuration
                    data_source = config.get('data_source', {})
                    domain = data_source.get('domain', [])
                    group_by = data_source.get('groupBy', {})
                    order_by = data_source.get('orderBy', {})

                    _logger.info("Generating table data for model: %s, with columns: %s",
                                model_name, columns)

                    try:
                        # Check if model exists
                        model_obj = request.env[model_name].sudo()

                        # Prepare fields to read from database
                        fields_to_read = []
                        for column in columns:
                            field_name = column.get('field')
                            if field_name:
                                fields_to_read.append(field_name)

                        # Build the order parameter for Odoo search
                        order = None
                        if order_by and order_by.get('field'):
                            direction = order_by.get('direction', 'asc')
                            order = f"{order_by.get('field')} {direction}"

                        # Handle groupby
                        if group_by and group_by.get('field'):
                            # In Odoo, we can implement groupby using read_group
                            groupby_field = group_by.get('field')
                            _logger.info("Using read_group with groupby: %s", groupby_field)

                            # Special case: if groupby field is 'id', we should not use read_group
                            # because it doesn't make sense to group by id (each record has a unique id)
                            # In this case, we'll use a regular search and read
                            if groupby_field == 'id':
                                _logger.info("Grouping by id detected, using regular search instead")
                                records = model_obj.search(domain, limit=page_size, order=order)

                                # Read the fields
                                data = []
                                if records:
                                    # Read all fields at once for better performance
                                    records_data = records.read(fields_to_read)

                                    # Post-process the data
                                    for record in records_data:
                                        row = {}
                                        for field_name in fields_to_read:
                                            field_value = record.get(field_name)
                                            field_info = model_obj._fields.get(field_name)

                                            # Handle different field types
                                            if field_info and field_info.type == 'many2one' and isinstance(field_value, (list, tuple)) and len(field_value) >= 2:
                                                # Many2one fields need to be formatted as {id, name} objects
                                                row[field_name] = {
                                                    'id': field_value[0],
                                                    'name': field_value[1]
                                                }
                                            else:
                                                # For other fields, use the value directly
                                                row[field_name] = field_value

                                        # Ajout du domain global (pas de groupby)
                                        row["odash.domain"] = domain + [["id", "=", record.get("id")]]
                                        data.append(row)
                            else:
                                # Fields to aggregate
                                aggregation_fields = []
                                for column in columns:
                                    field_name = column.get('field')
                                    if field_name and field_name != groupby_field:
                                        # Only add fields that can be aggregated
                                        field_info = model_obj._fields.get(field_name)
                                        if field_info and field_info.type in ['integer', 'float', 'monetary']:
                                            aggregation_fields.append(field_name)

                                # Build a valid orderby for read_group
                                # When using read_group, the orderby must be based on an aggregation field
                                # or the groupby field itself
                                read_group_orderby = None
                                if order_by and order_by.get('field'):
                                    order_field = order_by.get('field')
                                    direction = order_by.get('direction', 'asc')

                                    # Check if the order field is either the groupby field or an aggregation field
                                    if order_field == groupby_field:
                                        read_group_orderby = f"{order_field} {direction}"
                                    elif order_field in aggregation_fields:
                                        read_group_orderby = f"{order_field} {direction}"
                                    else:
                                        # Default to groupby field if order field is not compatible
                                        _logger.warning("Order field %s not compatible with read_group for groupby %s, using groupby field instead",
                                                    order_field, groupby_field)
                                        read_group_orderby = f"{groupby_field} asc"

                                # Get the results grouped by the field
                                groups = model_obj.read_group(
                                    domain=domain,
                                    fields=[groupby_field] + aggregation_fields,
                                    groupby=[groupby_field],
                                    orderby=read_group_orderby,
                                    limit=page_size
                                )

                                # Format the result for response
                                data = []
                                for group in groups:
                                    row = {}

                                    # Format the groupby field which is typically a many2one
                                    groupby_value = group.get(groupby_field)
                                    if isinstance(groupby_value, tuple) and len(groupby_value) >= 2:
                                        # Many2one fields return (id, name)
                                        row[groupby_field] = {
                                            'id': groupby_value[0],
                                            'name': groupby_value[1]
                                        }
                                    else:
                                        row[groupby_field] = groupby_value

                                    # Add aggregated values
                                    for field in aggregation_fields:
                                        row[field] = group.get(field)

                                    # Ajout du domain spécifique au groupe
                                    row["odash.domain"] = group.get("__domain", domain)
                                    data.append(row)
                        else:
                            # No groupby, just do a normal search and read
                            records = model_obj.search(domain, limit=page_size, order=order)

                            # Read the fields
                            data = []
                            if records:
                                # Read all fields at once for better performance
                                records_data = records.read(fields_to_read)

                                # Post-process the data
                                for record in records_data:
                                    row = {}
                                    for field_name in fields_to_read:
                                        field_value = record.get(field_name)
                                        field_info = model_obj._fields.get(field_name)

                                        # Handle different field types
                                        if field_info and field_info.type == 'many2one' and isinstance(field_value, (list, tuple)) and len(field_value) >= 2:
                                            # Many2one fields need to be formatted as {id, name} objects
                                            row[field_name] = {
                                                'id': field_value[0],
                                                'name': field_value[1]
                                            }
                                        else:
                                            # For other fields, use the value directly
                                            row[field_name] = field_value

                                    # Ajout du domain global (pas de groupby)
                                    row["odash.domain"] = domain + [["id", "=", record.get("id")]]
                                    data.append(row)

                    except Exception as e:
                        _logger.error("Error generating table data: %s", str(e))
                        # Return empty data on error
                        data = []

                    # Prepare response data
                    visualization_data = {
                        config_id: {
                            "data": data,
                        }
                    }

                elif visualization_type == 'block':
                    # Get real data for a block (KPI)
                    block_options = config.get('block_options', {})
                    field_name = block_options.get('field', 'id')
                    aggregation = block_options.get('aggregation', 'count')

                    _logger.info("Generating block data for model: %s, field: %s, aggregation: %s",
                                model_name, field_name, aggregation)

                    # Get domain from configuration
                    data_source = config.get('data_source', {})
                    domain = data_source.get('domain', [])

                    # Convert domain to Odoo format if needed
                    odoo_domain = domain

                    try:
                        # Check if model exists
                        model_obj = request.env[model_name].sudo()

                        # Check if field exists in the model
                        field_exists = field_name in model_obj._fields
                        if not field_exists and aggregation != 'count':
                            _logger.warning("Field %s not found in model %s, falling back to count",
                                            field_name, model_name)
                            aggregation = 'count'
                            field_name = 'id'  # Use id for count

                        # Calculate the aggregation using SQL
                        table_name = model_obj._table

                        # Build the SQL query based on the aggregation type
                        if aggregation == 'count':
                            # Simple count query
                            query = f"""
                                SELECT COUNT(*) as value 
                                FROM "{table_name}"
                            """
                            self._apply_sql_where_clause(query, model_name, odoo_domain)
                            result = request.env.cr.dictfetchone()
                            value = result.get('value', 0) if result else 0
                        elif aggregation == 'count_distinct':
                            # Count distinct values
                            query = f"""
                                SELECT COUNT(DISTINCT "{field_name}") as value 
                                FROM "{table_name}"
                            """
                            self._apply_sql_where_clause(query, model_name, odoo_domain)
                            result = request.env.cr.dictfetchone()
                            value = result.get('value', 0) if result else 0
                        elif aggregation in ['sum', 'avg', 'min', 'max']:
                            # Aggregation query
                            query = f"""
                                SELECT {aggregation.upper()}("{field_name}") as value 
                                FROM "{table_name}"
                                WHERE "{field_name}" IS NOT NULL
                            """
                            self._apply_sql_where_clause(query, model_name, odoo_domain)
                            result = request.env.cr.dictfetchone()
                            value = result.get('value', 0) if result else 0
                        else:
                            # Unsupported aggregation
                            _logger.warning("Unsupported aggregation: %s, using count", aggregation)
                            aggregation = 'count'
                            query = f"""
                                SELECT COUNT(*) as value 
                                FROM "{table_name}"
                            """
                            self._apply_sql_where_clause(query, model_name, odoo_domain)
                            result = request.env.cr.dictfetchone()
                            value = result.get('value', 0) if result else 0

                    except Exception as e:
                        _logger.error("Error executing query for block data: %s", str(e))
                        # Return a fallback value
                        value = 0

                    # Get field label for display
                    field_label = field_name
                    if field_exists:
                        field_info = model_obj._fields[field_name]
                        field_label = field_info.string or field_name

                    # Prepare response data
                    visualization_data = {
                        config_id: {
                            "data": {
                                "value": value,
                                "label": field_label,
                                "odash.domain": domain
                            },
                        }
                    }

                # Prepare response data
                response_data.append(visualization_data)

            # Check if we have response data
            if not response_data:
                return self._build_response({'success': False, 'error': 'No valid configuration data found'}, status=400)

            # Return the final response
            return self._build_response(response_data)

        except Exception as e:
            _logger.error("Error in API get_visualization_data: %s", str(e))
            return self._build_response({'success': False, 'error': str(e)}, status=500)

    @http.route(['/api/get/model_fields/<string:model_name>'], type='http', auth='api_key_dashboard', csrf=False, methods=['GET'], cors="*")
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
            fields_info = self._get_fields_info(model_obj)

            return ApiHelper.json_valid_response(fields_info, 200)

        except Exception as e:
            _logger.error("Error in API get_model_fields: %s", str(e))
            return self._build_response({'success': False, 'error': str(e)}, status=500)

    def _get_fields_info(self, model):
        """
        Get information about all fields of an Odoo model.
        
        :param model: Odoo model object
        :return: List of field information
        """
        fields_info = []

        # Get fields from the model
        fields_data = model.fields_get()

        # Fields to exclude
        excluded_field_types = ['binary', 'one2many', 'many2many', 'text']  # Binary fields like images in base64
        excluded_field_names = [
            '__last_update',
            'write_date', 'write_uid', 'create_uid',
        ]

        # Fields prefixed with these strings will be excluded
        excluded_prefixes = ['message_', 'activity_', 'has_', 'is_', 'x_studio_']

        for field_name, field_data in fields_data.items():
            field_type = field_data.get('type', 'unknown')

            # Skip fields that match our exclusion criteria
            if (field_type in excluded_field_types or
                field_name in excluded_field_names or
                any(field_name.startswith(prefix) for prefix in excluded_prefixes)):
                continue

            # Check if it's a computed field that's not stored
            field_obj = model._fields.get(field_name)
            if field_obj and field_obj.compute and not field_obj.store:
                _logger.debug("Skipping non-stored computed field: %s", field_name)
                continue

            # Create field info object for response
            field_info = {
                'field': field_name,
                'name': field_data.get('string', field_name),
                'type': field_type,
                'label': field_data.get('string', field_name),
                'value': field_name,
                'search': f"{field_name} {field_data.get('string', field_name)}"
            }

            # Add selection options if field is a selection
            if field_data.get('type') == 'selection' and 'selection' in field_data:
                field_info['selection'] = [
                    {'value': value, 'label': label}
                    for value, label in field_data['selection']
                ]

            fields_info.append(field_info)

        # Sort fields by name for better readability
        fields_info.sort(key=lambda x: x['name'])

        return fields_info

    def _extract_post_data(self, request, kw):
        """
        Extract and parse data from POST request body.
        
        :param request: HTTP request object
        :param kw: Additional keyword arguments
        :return: Parsed request parameters
        """
        try:
            # Try to parse JSON data from request body
            post_data = json.loads(request.httprequest.data.decode('utf-8'))
            # If we have a params field (standard JSON-RPC envelope), use that
            if 'params' in post_data:
                params = post_data.get('params', {})
            # Otherwise use the whole body
            else:
                params = post_data
        except Exception as e:
            _logger.warning("Failed to parse POST JSON data: %s", str(e))
            # If parsing fails, try to get form data
            params = dict(request.httprequest.form)

            # If still empty, try to use kw
            if not params:
                params = kw

        # Normalize to list if it's a single configuration
        if not isinstance(params, list):
            params = [params]

        return params

    def _build_response(self, data, status=200, error=None):
        """
        Build a standardized API response.
        
        :param data: Response data to include
        :param status: HTTP status code
        :param error: Optional error message
        :return: HTTP Response object
        """
        if error:
            response_data = {
                'success': False,
                'error': str(error)
            }
        else:
            response_data = data

        return ApiHelper.json_valid_response(response_data, status)

    def _apply_sql_where_clause(self, query, model_name, domain):
        """
        Apply SQL WHERE clause based on Odoo domain.
        
        :param query: SQL query to modify
        :param model_name: Model name for domain calculation
        :param domain: Odoo domain expression
        :return: Tuple of (modified query, if query was executed)
        """
        if not domain:
            request.env.cr.execute(query)
            return True

        where_clause, where_params = request.env[model_name].sudo()._where_calc(domain).where_clause
        if where_clause:
            # Check if the query already has a WHERE clause
            if ' WHERE ' in query:
                query += f" AND {where_clause}"
            else:
                query += f" WHERE {where_clause}"
            request.env.cr.execute(query, where_params)
        else:
            request.env.cr.execute(query)

        return True

    def _format_field_value(self, field_value, field_info):
        """
        Format field value based on field type for API response.
        
        :param field_value: Raw field value
        :param field_info: Field information object
        :return: Formatted field value
        """
        # Handle many2one fields which return (id, name) tuples
        if field_info and field_info.type == 'many2one' and isinstance(field_value, (list, tuple)) and len(field_value) >= 2:
            return {
                'id': field_value[0],
                'name': field_value[1]
            }
        # Handle other field types
        return field_value
