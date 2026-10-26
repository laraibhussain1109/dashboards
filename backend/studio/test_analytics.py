"""Known-result numerical, compatibility, edge-case and hostile-input tests."""
import json
import math
import unittest

from studio.analytics import Formula, aggregate, compatible, evaluate_formula, filter_rows, number, profile, query, recommend

ROWS = [
    {"Date": "2025-01-01", "Region": "North", "Product": "A", "Revenue": "100", "Cost": 60, "Units": 2, "Target": 110, "Customer ID": "001"},
    {"Date": "2025-01-15", "Region": "South", "Product": "B", "Revenue": "200", "Cost": 120, "Units": 4, "Target": 180, "Customer ID": "002"},
    {"Date": "2025-02-01", "Region": "North", "Product": "B", "Revenue": "300", "Cost": 210, "Units": 6, "Target": 250, "Customer ID": "003"},
    {"Date": "2025-02-15", "Region": "South", "Product": "A", "Revenue": None, "Cost": 0, "Units": 0, "Target": 0, "Customer ID": "004"},
]


class ProfilingTests(unittest.TestCase):
    def test_profile_types_missing_and_statistics(self):
        p = profile(ROWS)
        columns = {c["name"]: c for c in p["columns"]}
        self.assertEqual(p["row_count"], 4)
        self.assertEqual(p["column_count"], 8)
        self.assertEqual(columns["Customer ID"]["type"], "identifier")
        self.assertEqual(columns["Revenue"]["type"], "currency")
        self.assertEqual(columns["Date"]["type"], "date")
        self.assertEqual(columns["Revenue"]["missing"], 1)
        self.assertEqual(columns["Revenue"]["sum"], 600)
        self.assertEqual(columns["Revenue"]["mean"], 200)
        self.assertEqual(columns["Revenue"]["median"], 200)
        self.assertEqual(columns["Region"]["categories"], [{"value": "North", "count": 2}, {"value": "South", "count": 2}])
        self.assertTrue(p["relationships"])
        self.assertIn("Revenue: 25.0% missing values.", p["warnings"])

    def test_duplicates_empty_and_explicit_type_overrides(self):
        p = profile(ROWS + [ROWS[0]], {"Customer ID": "categorical"})
        self.assertEqual(p["duplicates"], 1)
        self.assertEqual(next(c for c in p["columns"] if c["name"] == "Customer ID")["type"], "categorical")
        self.assertEqual(profile([])["columns"], [])
        with self.assertRaisesRegex(ValueError, "Unknown"):
            profile(ROWS, {"Secret": "numeric"})
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            profile(ROWS, {"Revenue": "python"})

    def test_currency_percentages_and_nonfinite(self):
        self.assertEqual(number("$1,234.50"), 1234.5)
        self.assertEqual(number("(20)"), -20)
        self.assertEqual(number("25%"), .25)
        self.assertIsNone(number(float("inf")))
        self.assertIsNone(number("NaN"))
        p = profile([{"Rate": "20%"}, {"Rate": "30%"}, {"Rate": None}])
        self.assertEqual(p["columns"][0]["mean"], .25)
        json.dumps(p, allow_nan=False)

    def test_recommendations_cover_compatible_renderers_only(self):
        p = profile(ROWS)
        specs = recommend(p)
        enabled = {c["id"] for c in compatible(p) if c["compatible"]}
        recommended = {s["type"] for s in specs}
        self.assertEqual(enabled, recommended)
        self.assertIn("line", enabled)
        self.assertIn("scatter3d", enabled)
        self.assertNotIn("gantt", enabled)
        self.assertIn("pie3d", enabled)
        for spec in specs:
            with self.subTest(kind=spec["type"]):
                data = query(ROWS, spec, p)
                json.dumps(data, allow_nan=False)

    def test_sparse_single_category_and_text_only_recommendations(self):
        for rows in ([{"Category":"Only", "Amount":2}], [{"Text":"Hello"}, {"Text":"World"}], [{"Group":"Only", "Loss":-4}], [{"A":None}], []):
            p = profile(rows)
            for spec in recommend(p):
                with self.subTest(rows=rows,kind=spec["type"]):
                    query(rows,spec,p)

    def test_surface_recommendation_requires_a_real_coordinate_grid(self):
        p=profile([{"X":1,"Y":4,"Z":10},{"X":2,"Y":5,"Z":15},{"X":3,"Y":6,"Z":20}])
        self.assertFalse(next(c for c in compatible(p) if c["id"]=="surface3d")["compatible"])
        p=profile([{"X":1,"Y":1,"Z":10},{"X":1,"Y":2,"Z":15},{"X":2,"Y":1,"Z":20},{"X":2,"Y":2,"Z":25}])
        self.assertTrue(next(c for c in compatible(p) if c["id"]=="surface3d")["compatible"])

    def test_identifiers_are_not_measure_recommendations(self):
        p = profile([{"Customer ID": "0001", "Name": "Jane"}, {"Customer ID": "0002", "Name": "John"}])
        self.assertFalse(next(c for c in compatible(p) if c["id"] == "histogram")["compatible"])
        self.assertEqual(next(s for s in recommend(p) if s["type"] == "kpi")["aggregation"], "count")


class FormulaTests(unittest.TestCase):
    def test_arithmetic_aggregate_and_spaced_names(self):
        self.assertEqual(evaluate_formula("SUM(Revenue) - SUM(Cost)", ROWS), 210)
        self.assertEqual(evaluate_formula("Margin = (SUM(Revenue)-SUM(Cost))/SUM(Revenue)*100", ROWS), 35)
        self.assertEqual(evaluate_formula("Revenue / Units", ROWS), 50)
        self.assertEqual(evaluate_formula("COUNT([Customer ID])", ROWS), 4)
        self.assertEqual(evaluate_formula("DISTINCT_COUNT(Region)", ROWS), 2)
        self.assertEqual(evaluate_formula("AVG(Revenue)", ROWS), 200)
        self.assertEqual(evaluate_formula("MEDIAN(Revenue)", ROWS), 200)
        self.assertEqual(evaluate_formula("ROUND(AVG(Cost), 1)", ROWS), 97.5)
        self.assertEqual(evaluate_formula("SUM(Revenue-Cost)", ROWS), 210)

    def test_division_zero_missing_and_empty_aggregate(self):
        with self.assertRaisesRegex(ValueError, "Division by zero"):
            evaluate_formula("SUM(Revenue)/0", ROWS)
        self.assertIsNone(Formula("SUM(Revenue)", ["Revenue"]).evaluate([]))
        self.assertEqual(Formula("COUNT(Revenue)", ["Revenue"]).evaluate([]), 0)

    def test_hostile_formulas_are_rejected_without_execution(self):
        expressions = ["__import__('os').system('id')", "Revenue.__class__", "[x for x in Revenue]", "lambda: 1", "Revenue[0]", "open('/etc/passwd')", "SUM(Revenue, Cost)", "2**100000", "SUM(SUM(Revenue))", "'hello'", "True", "SUM(Missing)", "(1).__class__", "SUM(Revenue, bad=1)"]
        for expr in expressions:
            with self.subTest(expr=expr), self.assertRaises(ValueError):
                evaluate_formula(expr, ROWS)

    def test_calculated_fields_use_row_semantics_and_originals_are_not_mutated(self):
        result = query(ROWS, {"type": "kpi", "y": "Profit", "calculated_fields": [{"name": "Profit", "formula": "Revenue-Cost"}]})
        self.assertEqual(result["value"], 210)
        self.assertNotIn("Profit", ROWS[0])
        with self.assertRaisesRegex(ValueError, 'row-level arithmetic'):
            query(ROWS, {'type':'kpi','y':'RepeatedTotal','calculated_fields':[{'name':'RepeatedTotal','formula':'SUM(Revenue)'}]})


class FilterTests(unittest.TestCase):
    def test_and_or_include_and_exclude(self):
        filtered = filter_rows(ROWS, {"logic": "and", "conditions": [{"field": "Region", "op": "eq", "value": "North"}, {"logic": "or", "conditions": [{"field": "Units", "op": "gt", "value": 4}, {"field": "Product", "op": "eq", "value": "Z"}]}]})
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["Revenue"], "300")
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Region", "op": "in", "value": ["North"]}])), 2)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Region", "op": "not_in", "value": ["North"]}])), 2)

    def test_dates_numeric_ranges_nulls_and_search(self):
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Revenue", "op": "between", "value": [100, 200]}])), 2)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Date", "op": "date_range", "value": ["2025-01-01", "2025-01-31"]}])), 2)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Revenue", "op": "is_null"}])), 1)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Revenue", "op": "not_null"}])), 3)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Region", "op": "contains", "value": "NOR"}])), 2)
        self.assertEqual(len(filter_rows(ROWS, [{"field": "Units", "op": "gte", "value": "4"}])), 2)
        rows = [{"Date": "2025-01-31T23:59:59"}, {"Date": "2025-02-01T00:00:00"}]
        self.assertEqual(len(filter_rows(rows, [{"field": "Date", "op": "date_range", "value": [None,"2025-01-31"]}])), 1)

    def test_identifier_filters_preserve_leading_zeroes(self):
        rows=[{"Account ID":"001"},{"Account ID":"1"}]
        self.assertEqual(filter_rows(rows,[{"field":"Account ID","op":"eq","value":"001"}]),[rows[0]])

    def test_invalid_filter_fails_even_for_empty_data(self):
        with self.assertRaisesRegex(ValueError, "Missing filter"):
            filter_rows([], [{"field": "Nope", "op": "eq", "value": 1}])
        with self.assertRaisesRegex(ValueError, "Unsupported filter"):
            filter_rows([], [{"field": "Revenue", "op": "exec"}], ["Revenue"])
        with self.assertRaisesRegex(ValueError, "64"):
            filter_rows(ROWS, [{"field": "Revenue"}] * 65)


class QueryTests(unittest.TestCase):
    def test_shared_grouped_and_kpi_calculation_under_filters(self):
        spec = {"type": "bar", "x": "Region", "y": "Revenue", "aggregation": "sum", "filters": [{"field": "Units", "op": "gt", "value": 0}]}
        bars = query(ROWS, spec)
        kpi = query(ROWS, {**spec, "type": "kpi"})
        self.assertEqual(bars["labels"], ["North", "South"])
        self.assertEqual(bars["series"][0]["values"], [400, 200])
        self.assertEqual(sum(bars["series"][0]["values"]), kpi["value"])
        self.assertEqual(kpi["value"], 600)

    def test_count_average_median_distinct(self):
        self.assertEqual(aggregate(ROWS, "Revenue", "count"), 3)
        self.assertEqual(aggregate(ROWS, None, "count"), 4)
        self.assertEqual(aggregate(ROWS, "Revenue", "average"), 200)
        self.assertEqual(aggregate(ROWS, "Revenue", "median"), 200)
        self.assertEqual(aggregate(ROWS, "Region", "distinct_count"), 2)
        self.assertIsNone(aggregate([], "Revenue", "sum"))

    def test_ratio_percentage_growth_difference(self):
        base = {"type": "kpi", "y": "Revenue", "denominator": "Target"}
        self.assertAlmostEqual(query(ROWS, {**base, "aggregation": "ratio"})["value"], 600/540)
        self.assertAlmostEqual(query(ROWS, {**base, "aggregation": "percentage"})["value"], 600/540*100)
        self.assertAlmostEqual(query(ROWS, {**base, "aggregation": "growth"})["value"], 60/540*100)
        self.assertEqual(query(ROWS, {**base, "aggregation": "difference"})["value"], 60)
        self.assertEqual(query(ROWS, {"type": "kpi", "aggregation": "conditional_count", "y": "Revenue", "condition": [{"field": "Region", "op": "eq", "value": "North"}]})["value"], 2)

    def test_time_buckets_cumulative_moving_and_comparison(self):
        base = {"type": "line", "x": "Date", "y": "Revenue", "granularity": "month"}
        self.assertEqual(query(ROWS, base)["series"][0]["values"], [300,300])
        self.assertEqual(query(ROWS, {**base,"type":"cumulative"})["series"][0]["values"], [300,600])
        self.assertEqual(query(ROWS, {**base,"type":"moving_average","window":2})["series"][0]["values"], [300,300])
        kpi=query(ROWS, {**base,"type":"kpi","comparison":"mom"})
        self.assertEqual(kpi["value"],300)
        self.assertEqual(kpi["previous"],300)
        self.assertEqual(kpi["change"],0)

    def test_saved_filter_logic_and_date_alias_match_editor_queries(self):
        spec={"type":"kpi","y":"Revenue","filters":[{"field":"Region","op":"eq","value":"North"},{"field":"Revenue","op":"gte","value":200}],"filter_logic":"or"}
        self.assertEqual(query(ROWS,spec)["value"],600)
        result=query(ROWS,{"type":"line","x":"Date","y":"Revenue","time_granularity":"month"})
        self.assertEqual(result["labels"],["2025-01","2025-02"])
        result=query(ROWS,{"type":"line","x":"Date","y":"Revenue","time_granularity":"day","granularity":"month"})
        self.assertEqual(result["labels"],["2025-01","2025-02"])

    def test_multiseries_sorting_and_percentage(self):
        result=query(ROWS, {"type":"stacked_bar","x":"Region","y":"Revenue","series":"Product","sort":"value","direction":"desc"})
        self.assertEqual(result["labels"], ["North","South"])
        self.assertEqual(len(result["series"]),2)
        result=query(ROWS, {"type":"percent_bar","x":"Region","y":"Revenue","series":"Product"})
        for i in range(len(result["labels"])):
            self.assertAlmostEqual(sum(s["values"][i] or 0 for s in result["series"]),100)

    def test_table_projection_search_pagination(self):
        result=query(ROWS, {"type":"table","columns":["Region","Revenue"],"search":"north","page":2,"limit":1})
        self.assertEqual(result["total"],2)
        self.assertEqual(result["total_pages"],2)
        self.assertEqual(result["rows"],[{"Region":"North","Revenue":"300"}])
        self.assertNotIn("Customer ID", result["rows"][0])

    def test_scatter_3d_surface_sankey_and_correlation(self):
        result=query(ROWS,{"type":"scatter3d","x":"Revenue","y":"Cost","z":"Units"})
        self.assertEqual(len(result["rows"]),3)
        self.assertEqual(result["rows"][0]["Revenue"],100)
        surface=query(ROWS,{"type":"surface3d","x":"Units","y":"Cost","z":"Revenue"})
        self.assertEqual(len(surface["matrix"]),3)
        self.assertEqual(surface["matrix"][0][0],100)
        sankey=query(ROWS,{"type":"sankey","x":"Region","series":"Product","y":"Revenue"})
        self.assertEqual(sum(link["value"] for link in sankey["links"]),600)
        matrix=query(ROWS,{"type":"heatmap","measures":["Revenue","Units"]})
        self.assertAlmostEqual(matrix["matrix"][0][1],1)
        constant=query([{"A":1,"B":2},{"A":1,"B":3}],{"type":"heatmap","measures":["A","B"]})
        self.assertIsNone(constant["matrix"][0][1])

    def test_geographic_map_uses_exact_coordinates_and_rejects_invalid_sources(self):
        rows=[{"Latitude":"28.6139","Longitude":"77.2090","Revenue":"100","City":"Delhi"},{"Latitude":"19.0760","Longitude":"72.8777","Revenue":"200","City":"Mumbai"}]
        p=profile(rows)
        self.assertEqual(p["coordinate_candidates"],[{"x":"Longitude","y":"Latitude"}])
        self.assertTrue(next(c for c in compatible(p) if c["id"]=="map")["compatible"])
        spec=next(s for s in recommend(p) if s["type"]=="map")
        data=query(rows,spec,p)
        self.assertEqual(data["rows"][0]["Latitude"],28.6139)
        self.assertEqual(data["rows"][0]["Longitude"],77.2090)
        self.assertEqual(data["rows"][0]["Revenue"],100)
        for invalid in ([{"Latitude":91,"Longitude":10}],[{"Latitude":10,"Longitude":181}],[{"Latitude":"North","Longitude":10}]):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                query(invalid,{"type":"map","x":"Longitude","y":"Latitude"})
        self.assertFalse(next(c for c in compatible(profile([{"Latitude":91,"Longitude":10}])) if c["id"]=="map")["compatible"])
        with self.assertRaisesRegex(ValueError,"explicitly named"):
            query([{"Revenue":10,"Cost":20}],{"type":"map","x":"Revenue","y":"Cost"})

    def test_regression_uses_all_paired_points_with_known_linear_result(self):
        rows=[{"X":1,"Y":3,"Unrelated":None},{"X":2,"Y":5,"Unrelated":9},{"X":3,"Y":7,"Unrelated":8}]
        data=query(rows,{"type":"regression","x":"X","y":"Y","z":"Unrelated"})
        result=data["regression"]
        self.assertEqual(result["n"],3)
        self.assertAlmostEqual(result["slope"],2)
        self.assertAlmostEqual(result["intercept"],1)
        self.assertAlmostEqual(result["r_squared"],1)
        self.assertEqual(result["x"],[1,3])
        self.assertEqual(result["y"],[3,7])
        with self.assertRaisesRegex(ValueError,"distinct X"):
            query([{"X":1,"Y":3},{"X":1,"Y":4}],{"type":"regression","x":"X","y":"Y"})
        with self.assertRaisesRegex(ValueError,"at least two"):
            query([{"X":1,"Y":3}],{"type":"regression","x":"X","y":"Y"})

    def test_density_is_a_normalized_symmetric_estimate_of_real_values(self):
        data=query([{"Value":-1},{"Value":0},{"Value":1}],{"type":"density","y":"Value"})
        density=data["density"]
        self.assertEqual(density["n"],3)
        self.assertEqual(density["sample_size"],3)
        self.assertGreater(density["bandwidth"],0)
        self.assertEqual(len(density["x"]),128)
        self.assertEqual(len(density["y"]),128)
        self.assertTrue(all(value>=0 for value in density["y"]))
        for a,b in zip(density["y"],reversed(density["y"])):
            self.assertAlmostEqual(a,b)
        area=sum((b-a)*(va+vb)/2 for a,b,va,vb in zip(density["x"],density["x"][1:],density["y"],density["y"][1:]))
        self.assertAlmostEqual(area,1,delta=.005)
        with self.assertRaisesRegex(ValueError,"distinct"):
            query([{"Value":2},{"Value":2}],{"type":"density","y":"Value"})
        with self.assertRaisesRegex(ValueError,"distinct"):
            query([],{"type":"density","y":"Value"},schema={"columns":[{"name":"Value","type":"numeric"}]})

    def test_three_dimensional_pie_has_real_aggregate_inputs(self):
        data=query(ROWS,{"type":"pie3d","x":"Region","y":"Revenue"})
        self.assertEqual(data["labels"],["North","South"])
        self.assertEqual(data["series"][0]["values"],[400,200])
        self.assertEqual(sum(data["series"][0]["values"]),600)
        with self.assertRaisesRegex(ValueError,"non-negative"):
            query([{"Region":"N","Revenue":-1}],{"type":"pie3d","x":"Region","y":"Revenue"})
        p=profile([{"Region":"N","Revenue":-1}])
        self.assertFalse(next(c for c in compatible(p) if c["id"]=="pie3d")["compatible"])

    def test_invalid_references_config_and_negative_contributions(self):
        with self.assertRaisesRegex(ValueError,"Missing data"):
            query(ROWS,{"type":"line","x":"Missing","y":"Revenue"})
        with self.assertRaisesRegex(ValueError,"Unsupported visualization"):
            query(ROWS,{"type":"python"})
        with self.assertRaisesRegex(ValueError,"non-negative"):
            query([{"Region":"N","Revenue":-1}],{"type":"pie","x":"Region","y":"Revenue"})
        with self.assertRaisesRegex(ValueError,"Display limit"):
            query(ROWS,{"type":"table","limit":999999})
        with self.assertRaisesRegex(ValueError,"missing column"):
            query([], {"type":"kpi","formula":"SUM(Missing)"}, schema={"columns":[{"name":"Revenue","type":"numeric"}]})

    def test_malformed_query_shapes_return_actionable_validation_errors(self):
        for spec in ({"type":[]},{"type":"line","sort":{}},{"type":"table","limit":{}},{"type":"heatmap","measures":{}},{"type":"line","filters":[{"field":"Date","op":[]}]}):
            with self.subTest(spec=spec),self.assertRaises(ValueError):
                query(ROWS,spec)

    def test_empty_filtered_results_keep_valid_schema_and_finite_json(self):
        result=query(ROWS,{"type":"line","x":"Date","y":"Revenue","filters":[{"field":"Region","op":"eq","value":"Absent"}]})
        self.assertEqual(result["labels"],[])
        self.assertEqual(result["row_count"],0)
        json.dumps(result,allow_nan=False)
        result=query([], {"type":"table"}, schema={"columns":[{"name":"Revenue","type":"numeric"}]})
        self.assertEqual(result["columns"],["Revenue"])


if __name__ == "__main__":
    unittest.main()

class ProvidedIntervalAndChordTests(unittest.TestCase):
    def test_supplied_intervals_recommend_and_query_without_inference(self):
        rows = [{'Date':'2026-01-01','Value':10,'Lower':8,'Upper':12}, {'Date':'2026-02-01','Value':20,'Lower':16,'Upper':24}]
        metadata = profile(rows)
        spec = next(item for item in recommend(metadata) if item['type']=='confidence_band')
        result = query(rows,spec,metadata)
        self.assertEqual(result['bands'],{'lower':[8,16],'center':[10,20],'upper':[12,24]})
        self.assertEqual(result['interval_source'],'provided')
        for recommendation in recommend(metadata):
            query(rows,recommendation,metadata)
        with self.assertRaisesRegex(ValueError,'lower ≤ center'):
            query([{**rows[0],'Lower':11}],spec)
        with self.assertRaisesRegex(ValueError,'one observation'):
            query([rows[0],rows[0]],spec)
        with self.assertRaisesRegex(ValueError,'Missing data column'):
            query(rows,{**spec,'upper':'Private'})
        self.assertFalse(next(item for item in compatible(profile(ROWS)) if item['id']=='confidence_band')['compatible'])

    def test_chord_weights_match_actual_grouped_relationships(self):
        rows=[{'From':'North','To':'Retail','Amount':10},{'From':'North','To':'Retail','Amount':20},{'From':'South','To':'Online','Amount':5}]
        metadata=profile(rows)
        spec=next(item for item in recommend(metadata) if item['type']=='chord')
        result=query(rows,spec,metadata)
        self.assertEqual([link['value'] for link in result['links']],[30,5])
        self.assertEqual(sum(row['Amount'] for row in result['rows']),35)
        filtered=query(rows,{**spec,'filters':[{'field':'From','op':'eq','value':'North'}]},metadata)
        self.assertEqual(len(filtered['links']),1)
        self.assertEqual(filtered['links'][0]['value'],30)
        with self.assertRaisesRegex(ValueError,'negative'):
            query([{'From':'North','To':'Retail','Amount':-1}],spec,metadata)

class GoalCorrectnessTests(unittest.TestCase):
    def test_goal_recommendations_require_actual_targets_and_allow_manual_goals(self):
        metadata=profile(ROWS)
        spec=next(item for item in recommend(metadata) if item['type']=='gauge')
        self.assertEqual(spec['target_field'],'Target')
        self.assertEqual(query(ROWS,spec,metadata)['target'],540)
        plain=[{'Value':5},{'Value':10}]
        self.assertFalse(any(item['type'] in {'gauge','progress'} for item in recommend(profile(plain))))
        manual=query(plain,{'type':'progress','y':'Value','target':20})
        self.assertEqual((manual['value'],manual['target']),(15,20))
        with self.assertRaisesRegex(ValueError,'positive supplied target'):
            query(plain,{'type':'gauge','y':'Value'})
