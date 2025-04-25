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


    @http.route(['/api/get/dashboard'], type='http', auth='api_key_dashboard', csrf=False, methods=['POST'], cors="*")
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
                    
                    # Modification: groupBy devient un tableau d'objets
                    group_by_list = data_source.get('groupBy', [])
                    if isinstance(group_by_list, dict):  # Pour compatibilité avec l'ancien format
                        group_by_list = [group_by_list] if group_by_list else []
                        
                    # Modification: orderBy devient un tableau d'objets
                    order_by_list = data_source.get('orderBy', [])
                    if isinstance(order_by_list, dict):  # Pour compatibilité avec l'ancien format
                        order_by_list = [order_by_list] if order_by_list else []
                        
                    _logger.info("Generating graph data for model: %s, with measures: %s, groupby: %s",
                                model_name, measures, group_by_list)
                    
                    try:
                        # Check if model exists
                        model_obj = request.env[model_name].sudo()

                        # If no measures specified, use count
                        if not measures:
                            measures = [{'field': 'id', 'aggregation': 'count', 'displayName': 'Count'}]

                        # Fields to group by - support de multiple groupby
                        groupby_fields = []
                        
                        # Si group_by_list n'est pas vide, on l'utilise
                        if group_by_list:
                            for group_by in group_by_list:
                                field = group_by.get('field')
                                interval = group_by.get('interval')
                                
                                if field:
                                    # Nouveau format: field et interval sont séparés
                                    # Vérifier si on a un intervalle spécifié séparément
                                    if interval and ':' not in field:
                                        # Si le champ est un champ date et qu'un intervalle est spécifié
                                        field_obj = model_obj._fields.get(field)
                                        if field_obj and field_obj.type in ['date', 'datetime']:
                                            # Format pour Odoo: field:interval
                                            field_with_interval = f"{field}:{interval}"
                                            groupby_fields.append(field_with_interval)
                                        else:
                                            # Si ce n'est pas un champ date, on ignore l'intervalle
                                            _logger.warning(
                                                "Interval '%s' specified for non-date field '%s', ignoring interval",
                                                interval, field
                                            )
                                            groupby_fields.append(field)
                                    else:
                                        # Compatibilité avec l'ancien format où le field contient déjà l'intervalle
                                        groupby_fields.append(field)
                        
                        # Si aucun groupby n'est spécifié, on utilise create_date:month par défaut
                        if not groupby_fields:
                            groupby_fields.append('create_date:month')
                        
                        # Field to group by
                        #groupby_field = group_by.get('field') if group_by else None
                        #if not groupby_field:
                        #    # Default to grouping by creation month
                        #    groupby_field = 'create_date:month'

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
                        if order_by_list and len(order_by_list) > 0:
                            # On utilise le premier orderBy du tableau
                            first_order = order_by_list[0]
                            if first_order.get('field'):
                                orderby_field = first_order.get('field')
                                direction = first_order.get('direction', 'asc')
                                
                                # Vérifier si le champ de tri est valide pour read_group
                                # Dans read_group, l'orderby ne peut être que:
                                # 1. Le champ de groupby
                                # 2. Un champ agrégé
                                is_valid_orderby = False
                                
                                # Vérifier si c'est un champ de groupby
                                if orderby_field in groupby_fields:
                                    is_valid_orderby = True
                                    
                                # Vérifier si c'est un champ agrégé
                                elif orderby_field in aggregation_fields:
                                    is_valid_orderby = True
                                    
                                # Si valide, construire l'orderby
                                if is_valid_orderby:
                                    orderby = f"{orderby_field} {direction}"
                                else:
                                    _logger.warning(
                                        "Order field '%s' is not a valid groupby field nor aggregate. "
                                        "In read_group, you can only order by the groupby field or an aggregated field. "
                                        "Ignoring orderby.", orderby_field
                                    )
                        
                        # Limit number of data points (for performance)
                        limit = 100

                        # Get grouped data - support de multiple groupby
                        groups = model_obj.read_group(
                            domain=domain,
                            fields=aggregation_fields,
                            groupby=groupby_fields,
                            orderby=orderby,
                            limit=limit,
                            lazy=False
                        )

                        # Format data for response
                        data = []
                        
                        # Fonction pour extraire les valeurs de groupby dans un format standardisé
                        def extract_group_values(group, groupby_fields):
                            group_values = []
                            
                            for field in groupby_fields:
                                # Pour les champs date avec intervalle (ex: create_date:month)
                                if ':' in field:
                                    base_field, interval = field.split(':')
                                    group_value = group.get(field)
                                    if group_value:
                                        group_values.append(str(group_value))
                                    else:
                                        group_values.append("Undefined")
                                else:
                                    # Pour les champs standards
                                    group_value = group.get(field)
                                    if isinstance(group_value, tuple) and len(group_value) >= 2:
                                        # Many2one fields return (id, name)
                                        group_values.append(str(group_value[1]))
                                    else:
                                        # For other field types
                                        group_values.append(str(group_value) if group_value is not None else "Undefined")
                            
                            return group_values
                        
                        # Nouvelle structure pour regrouper par première valeur de groupby
                        grouped_data = {}
                        
                        for group in groups:
                            # Pour le premier groupby, on utilise la clé "key" 
                            # Pour les autres groupby, on ajoute la valeur après un pipe aux noms des champs
                            group_values = extract_group_values(group, groupby_fields)
                            
                            # Première valeur de groupby comme clé principale 
                            primary_key = group_values[0] if group_values else "Undefined"

                            # Récupérer le domaine pour le premier groupby uniquement
                            first_groupby_field = groupby_fields[0]

                            # Pour les champs date avec intervalle, extraire le nom de base
                            if ':' in first_groupby_field:
                                base_field, interval = first_groupby_field.split(':')
                                field_name = base_field
                            else:
                                field_name = first_groupby_field

                            # Obtenir la valeur du premier groupby pour ce groupe
                            group_value = group.get(first_groupby_field)
                            first_groupby_value = None

                            if isinstance(group_value, tuple) and len(group_value) >= 2:
                                # Si c'est un many2one, prendre l'ID
                                first_groupby_value = group_value[0]
                            else:
                                first_groupby_value = group_value

                            # Construire un domaine simplifié pour le premier groupby
                            if first_groupby_value is not None:
                                # On n'inclut pas le domain original, seulement la condition sur le premier groupby
                                first_groupby_domain = [[field_name, '=', first_groupby_value]]
                            else:
                                first_groupby_domain = []
                            
                            # Initialiser l'entrée dans grouped_data si elle n'existe pas
                            if primary_key not in grouped_data:
                                grouped_data[primary_key] = {
                                    "key": primary_key,
                                    "odash.domain": first_groupby_domain
                                }
                            
                            # Add measures
                            for measure in measures:
                                field_name = measure.get('field')
                                aggregation = measure.get('aggregation', 'sum')
                                
                                if field_name:
                                    measure_value = None
                                    
                                    # Key name depends on aggregation type
                                    if aggregation == 'count':
                                        # For count, Odoo automatically adds a special field
                                        if f"{groupby_fields[0]}_count" in group:
                                            measure_value = group.get(f"{groupby_fields[0]}_count", 0)
                                        else:
                                            measure_value = len(group.get('__domain', []))
                                    else:
                                        # For other aggregations, Odoo calculates automatically based on field type
                                        measure_value = group.get(field_name, 0)
                                    
                                    # Construction de la clé avec pipe pour groupby multiples
                                    if len(group_values) > 1:
                                        # Format: field_name|second_groupby|third_groupby|...
                                        field_key = field_name + '|' + '|'.join(group_values[1:])
                                    else:
                                        field_key = field_name
                                    
                                    # Add value to data point with field_key
                                    grouped_data[primary_key][field_key] = measure_value
                        
                        # Convertir le dictionnaire en liste
                        data = list(grouped_data.values())

                    except Exception as e:
                        _logger.error("Error generating graph data: %s", str(e))
                        # Retourner un objet d'erreur standardisé au lieu d'une valeur de fallback
                        return_data = {
                            'success': False,
                            'error': str(e)
                        }
                        return self._build_response(return_data, status=500)

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
                    
                    # Modification: groupBy devient un tableau d'objets
                    group_by_list = data_source.get('groupBy', [])
                    if isinstance(group_by_list, dict):  # Pour compatibilité avec l'ancien format
                        group_by_list = [group_by_list] if group_by_list else []
                        
                    # Modification: orderBy devient un tableau d'objets
                    order_by_list = data_source.get('orderBy', [])
                    if isinstance(order_by_list, dict):  # Pour compatibilité avec l'ancien format
                        order_by_list = [order_by_list] if order_by_list else []
                        
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
                        if order_by_list and len(order_by_list) > 0:
                            # On utilise le premier orderBy du tableau
                            first_order = order_by_list[0]
                            if first_order.get('field'):
                                direction = first_order.get('direction', 'asc')
                                order = f"{first_order.get('field')} {direction}"
                        
                        # Handle groupby
                        if group_by_list and len(group_by_list) > 0:
                            # In Odoo, we can implement groupby using read_group
                            groupby_fields = []
                            for group_by in group_by_list:
                                field = group_by.get('field')
                                interval = group_by.get('interval')
                                
                                if field:
                                    # Nouveau format: field et interval sont séparés
                                    # Vérifier si on a un intervalle spécifié séparément
                                    if interval and ':' not in field:
                                        # Si le champ est un champ date et qu'un intervalle est spécifié
                                        field_obj = model_obj._fields.get(field)
                                        if field_obj and field_obj.type in ['date', 'datetime']:
                                            # Format pour Odoo: field:interval
                                            field_with_interval = f"{field}:{interval}"
                                            groupby_fields.append(field_with_interval)
                                        else:
                                            # Si ce n'est pas un champ date, on ignore l'intervalle
                                            _logger.warning(
                                                "Interval '%s' specified for non-date field '%s', ignoring interval",
                                                interval, field
                                            )
                                            groupby_fields.append(field)
                                    else:
                                        # Compatibilité avec l'ancien format où le field contient déjà l'intervalle
                                        groupby_fields.append(field)
                            
                            # Si aucun groupby n'est spécifié, on ne fait pas de groupby
                            if not groupby_fields:
                                groupby_fields = []
                        
                            # Fields to aggregate
                            aggregation_fields = []
                            for column in columns:
                                field_name = column.get('field')
                                if field_name and field_name != groupby_fields[0]:
                                    # Only add fields that can be aggregated
                                    field_info = model_obj._fields.get(field_name)
                                    if field_info and field_info.type in ['integer', 'float', 'monetary']:
                                        aggregation_fields.append(field_name)

                            # Build a valid orderby for read_group
                            # When using read_group, the orderby must be based on an aggregation field
                            # or the groupby field itself
                            read_group_orderby = None
                            if order_by_list and len(order_by_list) > 0:
                                first_order = order_by_list[0]
                                order_field = first_order.get('field')
                                direction = first_order.get('direction', 'asc')

                                # Vérifier si le champ de tri est valide pour read_group
                                is_valid_orderby = False
                                
                                # Vérifier si c'est un champ de groupby
                                if groupby_fields and order_field == groupby_fields[0]:
                                    is_valid_orderby = True
                                    read_group_orderby = f"{order_field} {direction}"
                                    
                                # Vérifier si c'est un champ agrégé
                                elif order_field in aggregation_fields:
                                    is_valid_orderby = True
                                    read_group_orderby = f"{order_field} {direction}"
                                
                                # Si non valide, utiliser le groupby comme fallback
                                if not is_valid_orderby and groupby_fields:
                                    _logger.warning(
                                        "Order field '%s' is not a valid groupby field nor aggregate. "
                                        "Using groupby field as fallback.", order_field
                                    )
                                    read_group_orderby = f"{groupby_fields[0]} asc"
                        
                            # Get the results grouped by the field
                            groups = model_obj.read_group(
                                domain=domain,
                                fields=[groupby_fields[0]] + aggregation_fields,
                                groupby=[groupby_fields[0]],
                                orderby=read_group_orderby,
                                limit=page_size
                            )

                            # Format the result for response
                            data = []
                            for group in groups:
                                row = {}

                                # Format the groupby field which is typically a many2one
                                groupby_value = group.get(groupby_fields[0])
                                if isinstance(groupby_value, tuple) and len(groupby_value) >= 2:
                                    # Many2one fields return (id, name)
                                    row[groupby_fields[0]] = {
                                        'id': groupby_value[0],
                                        'name': groupby_value[1]
                                    }
                                else:
                                    row[groupby_fields[0]] = groupby_value

                                # Add aggregated values
                                for field in aggregation_fields:
                                    row[field] = group.get(field)

                                # Ajout du domaine spécifique au groupe
                                first_groupby_field = groupby_fields[0]

                                # Pour les champs date avec intervalle, extraire le nom de base
                                if ':' in first_groupby_field:
                                    base_field, interval = first_groupby_field.split(':')
                                    field_name = base_field
                                else:
                                    field_name = first_groupby_field

                                # Obtenir la valeur du premier groupby pour ce groupe
                                group_value = group.get(first_groupby_field)
                                first_groupby_value = None

                                if isinstance(group_value, tuple) and len(group_value) >= 2:
                                    # Si c'est un many2one, prendre l'ID
                                    first_groupby_value = group_value[0]
                                else:
                                    first_groupby_value = group_value

                                # Construire un domaine simplifié pour le premier groupby
                                if first_groupby_value is not None:
                                    row["odash.domain"] = [[field_name, '=', first_groupby_value]]
                                else:
                                    row["odash.domain"] = []
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

                                    # Ajout du domain spécifique à l'ID du record uniquement
                                    row["odash.domain"] = [["id", "=", record.get("id")]]
                                    data.append(row)

                    except Exception as e:
                        _logger.error("Error generating table data: %s", str(e))
                        # Retourner un objet d'erreur standardisé au lieu d'une valeur de fallback
                        return_data = {
                            'success': False,
                            'error': str(e)
                        }
                        return self._build_response(return_data, status=500)

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
                        # Retourner un objet d'erreur standardisé au lieu d'une valeur de fallback
                        return_data = {
                            'success': False,
                            'error': str(e)
                        }
                        return self._build_response(return_data, status=500)

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
                                "odash.domain": []
                            },
                        }
                    }

                # Prepare response data
                response_data.append(visualization_data)

            # Check if we have response data
            if not response_data:
                return self._build_response({'success': False, 'error': 'No valid configuration data found'}, status=400)

            # Return the final response
            return self._build_response({'success': True, 'data': response_data})

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

            return self._build_response({'success': True, 'data': fields_info}, 200)

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
