# Imports
from odoo import http, fields as odoo_fields 
from odoo.http import request, Response
from odoo.osv import expression 
import json
import logging
import itertools 
from datetime import datetime, date, time, timedelta
import calendar
import re
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

# Custom JSON encoder for handling dates
class OdashboardJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super(OdashboardJSONEncoder, self).default(obj)

class OdashAPI(http.Controller):
    
    def _build_response(self, data, status=200):
        """Build a consistent JSON response with the given data and status."""
        headers = {'Content-Type': 'application/json'}
        return Response(json.dumps(data, cls=OdashboardJSONEncoder), 
                       status=status, 
                       headers=headers)
    
    def _parse_date_from_string(self, date_str, return_range=False):
        """Parse a date string in various formats and return a datetime object.
        If return_range is True, return a tuple of start and end dates for period formats.
        """
        if not date_str:
            return None
        
        # Week pattern (e.g., W16 2025)
        week_pattern = re.compile(r'W(\d{1,2})\s+(\d{4})')
        week_match = week_pattern.match(date_str)
        if week_match:
            week_num = int(week_match.group(1))
            year = int(week_match.group(2))
            # Get the first day of the week
            first_day = datetime.strptime(f'{year}-{week_num}-1', '%Y-%W-%w').date()
            if return_range:
                last_day = first_day + timedelta(days=6)
                return first_day, last_day
            return first_day
        
        # Month pattern (e.g., January 2025 or 2025-01)
        month_pattern = re.compile(r'(\w+)\s+(\d{4})|(\d{4})-(\d{2})')
        month_match = month_pattern.match(date_str)
        if month_match:
            if month_match.group(1) and month_match.group(2):
                # Format: January 2025
                month_name = month_match.group(1)
                year = int(month_match.group(2))
                month_num = datetime.strptime(month_name, '%B').month
            else:
                # Format: 2025-01
                year = int(month_match.group(3))
                month_num = int(month_match.group(4))
            
            if return_range:
                first_day = date(year, month_num, 1)
                last_day = date(year, month_num, calendar.monthrange(year, month_num)[1])
                return first_day, last_day
            return date(year, month_num, 1)
        
        # Standard date format
        try:
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            if return_range:
                return parsed_date, parsed_date
            return parsed_date
        except ValueError:
            pass
        
        # ISO format
        try:
            parsed_date = datetime.fromisoformat(date_str).date()
            if return_range:
                return parsed_date, parsed_date
            return parsed_date
        except ValueError:
            pass
        
        return None
    
    def _get_field_values(self, model, field_name, domain=None):
        """Get all possible values for a field, used for show_empty functionality."""
        if not domain:
            domain = []
        
        field_info = model._fields.get(field_name)
        if not field_info:
            return []
        
        if field_info.type == 'selection':
            # Return all selection options
            return [key for key, _ in field_info.selection]
        
        elif field_info.type == 'many2one':
            # Return all possible values for the relation
            relation_model = model.env[field_info.comodel_name]
            rel_values = relation_model.search_read([], ['id', 'display_name'])
            return [{'id': r['id'], 'display_name': r['display_name']} for r in rel_values]
        
        elif field_info.type in ['date', 'datetime']:
            # This will be handled separately based on the data range and interval
            return []
        
        return []
    
    def _build_date_range(self, model, field_name, domain, interval='month'):
        """Build a range of dates for show_empty functionality."""
        # First get the min and max dates from the data
        if not domain:
            where_clause = "TRUE"
            where_params = []
        else:
            query = model._where_calc(domain)
            where_clause = query.where_clause and query.where_clause[0] or "TRUE"
            where_params = query.where_clause_params or []
        
        min_date_query = f"""
            SELECT MIN({field_name}::date) as min_date FROM {model._table}
            WHERE {where_clause}
        """
        request.env.cr.execute(min_date_query, where_params)
        min_date = request.env.cr.fetchone()[0] or date.today()
        
        max_date_query = f"""
            SELECT MAX({field_name}::date) as max_date FROM {model._table}
            WHERE {where_clause}
        """
        request.env.cr.execute(max_date_query, where_params)
        max_date = request.env.cr.fetchone()[0] or date.today()
        
        # Generate all intermediate dates based on interval
        date_values = []
        current_date = min_date
        
        if interval == 'day':
            delta = timedelta(days=1)
            format_str = '%Y-%m-%d'
        elif interval == 'week':
            delta = timedelta(weeks=1)
            # Use ISO week format
            format_str = 'W%W %Y'
        elif interval == 'month':
            # For months, use a relative delta
            delta = relativedelta(months=1)
            format_str = '%Y-%m'
        elif interval == 'quarter':
            delta = relativedelta(months=3)
            # Custom handling for quarters
            format_str = 'Q%q %Y'
        elif interval == 'year':
            delta = relativedelta(years=1)
            format_str = '%Y'
        else:
            # Default to month
            delta = relativedelta(months=1)
            format_str = '%Y-%m'
        
        while current_date <= max_date:
            # Format based on interval
            if interval == 'week':
                date_values.append(f"W{current_date.isocalendar()[1]} {current_date.year}")
            elif interval == 'quarter':
                quarter = (current_date.month - 1) // 3 + 1
                date_values.append(f"Q{quarter} {current_date.year}")
            else:
                date_values.append(current_date.strftime(format_str))
            
            # Move to next date
            current_date += delta
        
        return date_values
    
    def _generate_empty_combinations(self, model, group_by_list, domain):
        """Generate all combinations for fields with show_empty=True."""
        show_empty_fields = []
        all_values = {}
        
        # Identify fields with show_empty and get their values
        for gb in group_by_list:
            field = gb.get('field')
            show_empty = gb.get('show_empty', False)
            
            if show_empty and field:
                interval = gb.get('interval')
                show_empty_fields.append((field, interval))
                
                if model._fields[field].type in ['date', 'datetime']:
                    # For date fields, generate range
                    all_values[(field, interval)] = self._build_date_range(
                        model, field, domain, interval or 'month'
                    )
                else:
                    # For other fields, get all possible values
                    all_values[(field, interval)] = self._get_field_values(model, field, domain)
        
        if not show_empty_fields:
            return []
        
        # Generate all combinations
        fields_to_combine = [all_values.get((f, i), []) for f, i in show_empty_fields]
        field_names = [f for f, _ in show_empty_fields]
        
        # Use itertools.product to get all combinations
        combinations = list(itertools.product(*fields_to_combine))
        return [dict(zip(field_names, combo)) for combo in combinations]
    
    def _handle_show_empty(self, results, model, group_by_list, domain, measures=None):
        """Handle show_empty for groupBy fields by filling in missing combinations."""
        if not any(gb.get('show_empty', False) for gb in group_by_list):
            return results  # No show_empty, return original results
        
        # Generate all possible combinations for show_empty fields
        all_combinations = self._generate_empty_combinations(model, group_by_list, domain)
        if not all_combinations:
            return results
        
        # Create a dictionary for easy lookup of existing results
        existing_results = {}
        for result in results:
            # Create a key based on groupby field values
            key_parts = []
            for gb in group_by_list:
                field = gb.get('field')
                if field:
                    key_parts.append(str(result.get(field)))
            
            existing_results[tuple(key_parts)] = result
        
        # Create combined results with empty values for missing combinations
        combined_results = []
        
        for combo in all_combinations:
            # Create a key to check if this combination exists in results
            key_parts = []
            for gb in group_by_list:
                field = gb.get('field')
                if field:
                    key_parts.append(str(combo.get(field, '')))
            
            combo_key = tuple(key_parts)
            
            if combo_key in existing_results:
                # Use existing result
                combined_results.append(existing_results[combo_key])
            else:
                # Create a new result with zero values for measures
                new_result = combo.copy()
                
                # Set all measures to 0
                if measures:
                    for measure in measures:
                        field = measure.get('field')
                        if field:
                            new_result[field] = 0
                
                # Add the new result
                combined_results.append(new_result)
        
        return combined_results
    
    def _build_odash_domain(self, group_by_values):
        """Build odash.domain for a specific data point based on groupby values.
        Returns only the specific domain for this data point, not including the base domain.
        """
        domain = []
        
        for field, value in group_by_values.items():
            if isinstance(value, str) and re.match(r'W\d{1,2}\s+\d{4}', value):
                # Handle week format by getting date range
                start_date, end_date = self._parse_date_from_string(value, return_range=True)
                domain.append([field, '>=', start_date.isoformat()])
                domain.append([field, '<=', end_date.isoformat()])
            elif field.endswith(':month') or field.endswith(':week') or field.endswith(':day') or field.endswith(':year'):
                # Handle date intervals
                base_field = field.split(':')[0]
                interval = field.split(':')[1]
                
                if interval == 'month' and re.match(r'\d{4}-\d{2}', str(value)):
                    year, month = str(value).split('-')
                    start_date = date(int(year), int(month), 1)
                    end_date = date(int(year), int(month), calendar.monthrange(int(year), int(month))[1])
                    domain.append([base_field, '>=', start_date.isoformat()])
                    domain.append([base_field, '<=', end_date.isoformat()])
                else:
                    # Direct comparison for other formats
                    domain.append([field, '=', value])
            else:
                # Regular field
                domain.append([field, '=', value])
        
        # Return empty list if domain is identical to base_domain
        return domain if domain else []
    
    def _process_block(self, model, domain, config):
        """Process block type visualization."""
        block_options = config.get('block_options', {})
        field = block_options.get('field')
        aggregation = block_options.get('aggregation', 'sum')
        label = block_options.get('label', field)
        
        if not field:
            return {'error': 'Missing field in block_options'}
        
        # Compute the aggregated value
        if aggregation == 'count':
            count = model.search_count(domain)
            return {
                'data': {
                    'value': count,
                    'label': label or 'Count',
                    'odash.domain': []
                }
            }
        else:
            # For sum, avg, min, max
            try:
                # Use SQL for better performance on large datasets
                agg_func = aggregation.upper()
                if not domain:
                    where_clause = "TRUE"
                    where_params = []
                else:
                    query = model._where_calc(domain)
                    where_clause = query.where_clause and query.where_clause[0] or "TRUE"
                    where_params = query.where_clause_params or []
                    
                query = f"""
                    SELECT {agg_func}({field}) as value
                    FROM {model._table}
                    WHERE {where_clause}
                """
                request.env.cr.execute(query, where_params)
                value = request.env.cr.fetchone()[0] or 0
                
                return {
                    'data': {
                        'value': value,
                        'label': label or f'{aggregation.capitalize()} of {field}',
                        'odash.domain': []
                    }
                }
            except Exception as e:
                _logger.error("Error calculating block value: %s", e)
                return {'error': f'Error calculating {aggregation} for {field}: {str(e)}'}
    
    def _process_graph(self, model, domain, group_by_list, order_string, config):
        """Process graph type visualization."""
        graph_options = config.get('graph_options', {})
        measures = graph_options.get('measures', [])
        
        if not group_by_list:
            return {'error': 'Missing groupBy configuration for graph'}
        
        if not measures:
            # Default to count measure if not specified
            measures = [{'field': 'id', 'aggregation': 'count'}]
        
        # Prepare groupby fields for read_group
        groupby_fields = []
        for gb in group_by_list:
            field = gb.get('field')
            interval = gb.get('interval')
            if field:
                groupby_fields.append(f"{field}:{interval}" if interval else field)
        
        # Prepare measure fields for read_group
        measure_fields = []
        for measure in measures:
            field = measure.get('field')
            agg = measure.get('aggregation', 'sum')
            if field and agg != 'count':
                measure_fields.append(field)
        
        # Execute read_group
        try:
            results = model.read_group(
                domain,
                fields=measure_fields,
                groupby=groupby_fields,
                orderby=order_string,
                lazy=False
            )
            
            # Handle show_empty if needed
            has_show_empty = any(gb.get('show_empty', False) for gb in group_by_list)
            if has_show_empty:
                results = self._handle_show_empty(results, model, group_by_list, domain, measures)
            
            # Transform results into the expected format
            transformed_data = self._transform_graph_data(results, group_by_list, measures, domain)
            
            return {'data': transformed_data}
            
        except Exception as e:
            _logger.exception("Error in _process_graph: %s", e)
            return {'error': f'Error processing graph data: {str(e)}'}
    
    def _transform_graph_data(self, results, group_by_list, measures, base_domain):
        """Transform read_group results into the expected format for graph visualization."""
        # Determine the primary grouping field (first in the list)
        primary_field = group_by_list[0].get('field') if group_by_list else None
        if not primary_field:
            return []
        
        # Get the interval if any
        primary_interval = group_by_list[0].get('interval')
        primary_field_with_interval = f"{primary_field}:{primary_interval}" if primary_interval else primary_field
        
        # Process secondary groupings (if any)
        secondary_fields = []
        for i, gb in enumerate(group_by_list[1:], 1):
            field = gb.get('field')
            interval = gb.get('interval')
            if field:
                field_with_interval = f"{field}:{interval}" if interval else field
                secondary_fields.append((field, field_with_interval))
        
        # Initialize output data
        transformed_data = []
        
        # Group by primary field first
        primary_groups = {}
        for result in results:
            # Extract the primary field value
            primary_value = result.get(primary_field_with_interval)
            if primary_field_with_interval in result:
                # Sometimes read_group adds suffixes to the field names
                primary_value = result[primary_field_with_interval]
            
            # Format primary value if it's a many2one field (tuple with id and name)
            formatted_primary_value = primary_value
            if isinstance(primary_value, tuple) and len(primary_value) == 2:
                # For many2one fields, extract just the display name
                formatted_primary_value = primary_value[1]
                
            # Create or get the group for this primary value
            if primary_value not in primary_groups:
                primary_groups[primary_value] = {
                    'key': str(formatted_primary_value),
                    'odash.domain': self._build_odash_domain({primary_field: primary_value})
                }
            
            # Process secondary fields and measures
            for sec_field, sec_field_with_interval in secondary_fields:
                sec_value = result.get(sec_field_with_interval)
                
                # Add measure values with secondary field in the key
                for measure in measures:
                    field = measure.get('field')
                    agg = measure.get('aggregation', 'sum')
                    
                    # Format the secondary field value correctly
                    formatted_sec_value = sec_value
                    if sec_value and isinstance(sec_value, tuple) and len(sec_value) == 2:
                        # For many2one fields, we get a tuple (id, name)
                        # Extract just the display name for cleaner output
                        formatted_sec_value = sec_value[1]
                    
                    # Construct the key for this measure and secondary field value
                    measure_key = f"{field}|{formatted_sec_value}" if sec_field else field
                    
                    # Get the measure value from the result
                    if agg == 'count':
                        measure_value = result.get('__count', 0)
                    else:
                        measure_value = result.get(field, 0)
                    
                    # Add to the primary group
                    primary_groups[primary_value][measure_key] = measure_value
        
        # Convert the dictionary to a list
        transformed_data = list(primary_groups.values())
        
        return transformed_data
    
    def _process_table(self, model, domain, group_by_list, order_string, config):
        """Process table type visualization."""
        table_options = config.get('table_options', {})
        columns = table_options.get('columns', [])
        limit = table_options.get('limit', 50)
        offset = table_options.get('offset', 0)
        
        if not columns:
            return {'error': 'Missing columns configuration for table'}
        
        # Extract fields to read
        fields_to_read = [col.get('field') for col in columns if col.get('field')]
        
        # Check if grouping is required
        if group_by_list:
            # Table with grouping - use read_group
            groupby_fields = []
            has_show_empty = any(gb.get('show_empty', False) for gb in group_by_list)
            
            for gb in group_by_list:
                field = gb.get('field')
                interval = gb.get('interval')
                if field:
                    groupby_fields.append(f"{field}:{interval}" if interval else field)
                    if field not in fields_to_read:
                        fields_to_read.append(field)
            
            if not groupby_fields:
                return {'error': "Invalid 'groupBy' configuration for grouped table"}
            
            # Add __count field for the counts per group
            fields_to_read.append('__count')
            
            try:
                # Execute read_group
                results = model.read_group(
                    domain,
                    fields=fields_to_read,
                    groupby=groupby_fields,
                    orderby=order_string,
                    lazy=False
                )
                
                # Handle show_empty if needed
                if has_show_empty:
                    results = self._handle_show_empty(results, model, group_by_list, domain)
                
                # Format for table display
                total_count = len(results)
                results = results[offset:offset+limit] if limit else results
                
                # Add domain for each row
                for result in results:
                    row_domain = list(domain)  # Start with base domain
                    
                    # Add domain elements for each groupby field
                    for gb_field in groupby_fields:
                        base_field = gb_field.split(':')[0] if ':' in gb_field else gb_field
                        value = result.get(gb_field)
                        
                        if value is not None:
                            if gb_field.endswith(':month') or gb_field.endswith(':week') or gb_field.endswith(':day') or gb_field.endswith(':year'):
                                # Handle date intervals
                                base_field = gb_field.split(':')[0]
                                interval = gb_field.split(':')[1]
                                
                                # Parse the date and build a range domain
                                date_start, date_end = self._parse_date_from_string(str(value), return_range=True)
                                if date_start and date_end:
                                    row_domain.append([base_field, '>=', date_start.isoformat()])
                                    row_domain.append([base_field, '<=', date_end.isoformat()])
                            else:
                                # Direct comparison for regular fields
                                row_domain.append([base_field, '=', value])
                    
                    result['odash.domain'] = row_domain
                
                return {
                    'data': results,
                    'metadata': {
                        'page': offset // limit + 1 if limit else 1,
                        'limit': limit,
                        'total_count': total_count
                    }
                }
                
            except Exception as e:
                _logger.exception("Error in _process_table with groupBy: %s", e)
                return {'error': f'Error processing grouped table: {str(e)}'}
        
        else:
            # Simple table - use search_read
            try:
                # Count total records for pagination
                total_count = model.search_count(domain)
                
                # Fetch the records
                records = model.search_read(
                    domain,
                    fields=fields_to_read,
                    limit=limit,
                    offset=offset,
                    order=order_string
                )
                
                # Add domain for each record
                for record in records:
                    record['odash.domain'] = expression.AND([[('id', '=', record['id'])], domain])
                
                return {
                    'data': records,
                    'metadata': {
                        'page': offset // limit + 1 if limit else 1,
                        'limit': limit,
                        'total_count': total_count
                    }
                }
                
            except Exception as e:
                _logger.exception("Error in _process_table: %s", e)
                return {'error': f'Error processing table: {str(e)}'}
    
    def _process_sql_request(self, sql_request, viz_type, config):
        """Process a SQL request with security measures."""
        # SECURITY WARNING: Direct SQL execution from API requests is risky.
        # This implementation includes safeguards but should be further reviewed.
        
        config_id = config.get('id')
        try:
            # Check for dangerous keywords (basic sanitization)
            dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'ALTER', 'TRUNCATE']
            has_dangerous_keyword = any(keyword in sql_request.upper() for keyword in dangerous_keywords)
            
            if has_dangerous_keyword:
                _logger.warning("Dangerous SQL detected for config ID %s: %s", config_id, sql_request)
                return {'error': 'SQL contains prohibited operations'}
            
            # Execute the SQL query (with LIMIT safeguard)
            if 'LIMIT' not in sql_request.upper():
                sql_request += " LIMIT 1000"  # Default limit for safety
            
            try:
                request.env.cr.execute(sql_request)
                results = request.env.cr.dictfetchall()
                
                # Format data based on visualization type
                if viz_type == 'graph':
                    return {'data': results}  # Simple pass-through for now
                elif viz_type == 'table':
                    return {'data': results, 'metadata': {'total_count': len(results)}}
                
            except Exception as e:
                _logger.error("SQL execution error: %s", e)
                return {'error': f'SQL error: {str(e)}'}
                
        except Exception as e:
            _logger.exception("Error in _process_sql_request:")
            return {'error': str(e)}
        
        return {'error': 'Unexpected error in SQL processing'}
    
    @http.route('/api/get/dashboard', type='http', auth='none', csrf=False, methods=['POST'], cors='*')
    def get_dashboard_data(self):
        """Main endpoint to get dashboard visualization data.
        Accepts JSON configurations for blocks, graphs, and tables.
        """
        results = {}
        
        try:
            # Parse JSON request data
            try:
                request_data = json.loads(request.httprequest.data.decode('utf-8'))
                if not isinstance(request_data, list):
                    request_data = [request_data]
            except Exception as e:
                _logger.error("Error parsing JSON data: %s", e)
                return self._build_response({'error': 'Invalid JSON format'}, 400)
                
            # Process each visualization request
            for config in request_data:
                config_id = config.get('id')
                if not config_id:
                    continue
                    
                try:
                    # Extract configuration parameters
                    viz_type = config.get('type')
                    model_name = config.get('model')
                    data_source = config.get('data_source', {})
                    
                    # Validate essential parameters
                    if not all([viz_type, model_name]):
                        results[config_id] = {'error': 'Missing required parameters: type, model'}
                        continue
                        
                    # Check if model exists
                    try:
                        model = request.env[model_name].sudo()
                    except KeyError:
                        results[config_id] = {'error': f'Model not found: {model_name}'}
                        continue
                    
                    # Extract common parameters
                    domain = data_source.get('domain', [])
                    group_by = data_source.get('groupBy', [])
                    order_by = data_source.get('orderBy', {})
                    order_string = None
                    if order_by:
                        field = order_by.get('field')
                        direction = order_by.get('direction', 'asc')
                        if field:
                            order_string = f"{field} {direction}"
                    
                    # Check if SQL request is provided
                    sql_request = data_source.get('sqlRequest')
                    
                    # Process based on visualization type
                    if sql_request and viz_type in ['graph', 'table']:
                        # Handle SQL request (with security measures)
                        results[config_id] = self._process_sql_request(sql_request, viz_type, config)
                    elif viz_type == 'block':
                        results[config_id] = self._process_block(model, domain, config)
                    elif viz_type == 'graph':
                        results[config_id] = self._process_graph(model, domain, group_by, order_string, config)
                    elif viz_type == 'table':
                        results[config_id] = self._process_table(model, domain, group_by, order_string, config)
                    else:
                        results[config_id] = {'error': f'Unsupported visualization type: {viz_type}'}
                        
                except Exception as e:
                    _logger.exception("Error processing visualization %s:", config_id)
                    results[config_id] = {'error': str(e)}
            
            return self._build_response(results)
            
        except Exception as e:
            _logger.exception("Unhandled error in get_dashboard_data:")
            return self._build_response({'error': str(e)}, 500)