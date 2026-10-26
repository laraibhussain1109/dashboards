/** Charts listed here have real renderers. Unsupported forms are never offered. */
export interface ChartType {
  id: string;
  name: string;
  group: string;
  description?: string;
}

export const CHART_TYPES: ChartType[] = [
  { id: 'bar', name: 'Column chart', group: 'Comparisons' },
  { id: 'horizontal_bar', name: 'Horizontal bars', group: 'Comparisons' },
  { id: 'grouped_bar', name: 'Grouped bars', group: 'Comparisons' },
  { id: 'stacked_bar', name: 'Stacked bars', group: 'Comparisons' },
  { id: 'percent_bar', name: '100% stacked bars', group: 'Comparisons' },
  { id: 'ranking', name: 'Ranking', group: 'Comparisons' },
  { id: 'line', name: 'Line chart', group: 'Trends' },
  { id: 'smooth_line', name: 'Smooth line', group: 'Trends' },
  { id: 'step_line', name: 'Step line', group: 'Trends' },
  { id: 'area', name: 'Area chart', group: 'Trends' },
  { id: 'stacked_area', name: 'Stacked area', group: 'Trends' },
  { id: 'cumulative', name: 'Cumulative trend', group: 'Trends' },
  { id: 'moving_average', name: 'Moving average', group: 'Trends' },
  { id: 'confidence_band', name: 'Provided interval band', group: 'Trends', description: 'Displays actual lower and upper interval fields; no interval is inferred.' },
  { id: 'pie', name: 'Pie chart', group: 'Contribution' },
  { id: 'donut', name: 'Doughnut chart', group: 'Contribution' },
  { id: 'semi_donut', name: 'Semi-doughnut', group: 'Contribution' },
  { id: 'treemap', name: 'Treemap', group: 'Contribution' },
  { id: 'sunburst', name: 'Sunburst', group: 'Contribution' },
  { id: 'histogram', name: 'Histogram', group: 'Distributions' },
  { id: 'density', name: 'Density curve', group: 'Distributions' },
  { id: 'box', name: 'Box plot', group: 'Distributions' },
  { id: 'violin', name: 'Violin plot', group: 'Distributions' },
  { id: 'scatter', name: 'Scatter plot', group: 'Relationships' },
  { id: 'regression', name: 'Regression trend', group: 'Relationships' },
  { id: 'bubble', name: 'Bubble chart', group: 'Relationships' },
  { id: 'heatmap', name: 'Correlation heatmap', group: 'Relationships' },
  { id: 'pareto', name: 'Pareto analysis', group: 'Business' },
  { id: 'waterfall', name: 'Waterfall', group: 'Business' },
  { id: 'funnel', name: 'Funnel', group: 'Business' },
  { id: 'gauge', name: 'Gauge', group: 'Business' },
  { id: 'bullet', name: 'Bullet chart', group: 'Business' },
  { id: 'radar', name: 'Radar chart', group: 'Business' },
  { id: 'progress', name: 'Progress to target', group: 'Business' },
  { id: 'kpi', name: 'KPI card', group: 'KPIs' },
  { id: 'table', name: 'Data table', group: 'Tables' },
  { id: 'pivot', name: 'Pivot table', group: 'Tables' },
  { id: 'summary', name: 'Summary table', group: 'Tables' },
  { id: 'sankey', name: 'Sankey flow', group: 'Advanced' },
  { id: 'chord', name: 'Weighted chord diagram', group: 'Advanced' },
  { id: 'map', name: 'Geographic coordinates', group: 'Geographic', description: 'Actual latitude and longitude coordinates on an offline world map.' },
  { id: 'calendar', name: 'Calendar heatmap', group: 'Advanced' },
  { id: 'timeline', name: 'Timeline', group: 'Advanced' },
  { id: 'gantt', name: 'Gantt chart', group: 'Advanced' },
  { id: 'scatter3d', name: '3D scatter', group: '3D' },
  { id: 'pie3d', name: '3D pie', group: '3D', description: 'Extruded three-dimensional wedges sized from category totals.' },
  { id: 'surface3d', name: '3D surface', group: '3D' },
  { id: 'bar3d', name: '3D bars', group: '3D' },
];

export const chartTypes = CHART_TYPES;
export const CHART_GROUPS = Array.from(new Set(CHART_TYPES.map((chart) => chart.group)));
export const chartName = (id: string) => CHART_TYPES.find((chart) => chart.id === id)?.name ?? id;
export const TABLE_TYPES = new Set(['table', 'pivot', 'summary']);
export const THREE_D_TYPES = new Set(['scatter3d', 'pie3d', 'surface3d', 'bar3d']);
