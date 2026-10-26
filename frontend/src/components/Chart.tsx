import React, { Component, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { Download, Maximize2, Search, ArrowUpDown, ChevronLeft, ChevronRight } from 'lucide-react';
import type { Widget, QueryResult, Theme } from '../types';
import { TABLE_TYPES, THREE_D_TYPES, chartName } from '../chartTypes';

const Plot = lazy(async () => {
  const [factory, bundle] = await Promise.all([
    import('react-plotly.js/factory'),
    import('plotly.js-dist-min'),
  ]);
  return { default: factory.default(bundle.default) };
});

type AnyRecord = Record<string, any>;
type Figure = { data: AnyRecord[]; layout: AnyRecord };
type ChartProps = { widget: Widget; data: QueryResult; theme?: Theme; onSelect?: (field: string, value: unknown, additional?: { field: string; value: unknown }[]) => void };
const DEFAULT_PALETTE = ['#4f46e5', '#06b6d4', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#f97316', '#64748b'];
const number = (value: unknown): number | null => value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
const values = (data: AnyRecord) => (data.series?.[0]?.values ?? []) as unknown[];
const fieldValues = (data: AnyRecord, field: string | undefined) => (data.rows ?? []).map((row: AnyRecord) => row[field ?? '']);
const paletteFor = (widget: AnyRecord, theme: AnyRecord) => Array.isArray(widget.colors) && widget.colors.length ? widget.colors : Array.isArray(widget.palette) && widget.palette.length ? widget.palette : Array.isArray(theme.palette) && theme.palette.length ? theme.palette : DEFAULT_PALETTE;
const truthy = (value: unknown, fallback = true) => value === undefined ? fallback : !!value;

export function formatValue(value: unknown, widget: AnyRecord = {}): string {
  const numeric = number(value);
  if (numeric === null) return value === null || value === undefined ? '—' : String(value);
  const precision = Math.max(0, Math.min(10, Number(widget.decimals ?? 2)));
  const options: Intl.NumberFormatOptions = { maximumFractionDigits: precision };
  if (widget.number_format === 'currency') {
    options.style = 'currency';
    options.currency = /^[A-Z]{3}$/.test(String(widget.currency ?? 'USD')) ? widget.currency ?? 'USD' : 'USD';
  }
  // KPI percentage formulas return percentage points, not a fraction.
  const formatted = new Intl.NumberFormat('en-US', options).format(numeric);
  return `${widget.prefix ?? ''}${formatted}${widget.number_format === 'percent' ? '%' : ''}${widget.suffix ?? ''}`;
}

function meshBars(data: AnyRecord, widget: AnyRecord, palette: string[]): AnyRecord {
  const sourceRows: AnyRecord[] = data.rows ?? [];
  const xlabels: unknown[] = data.x_values ?? data.x ?? (data.labels?.length ? data.labels : [...new Set(sourceRows.map((row) => row[widget.x]))].sort((a, b) => Number(a) - Number(b)));
  const ylabels: unknown[] = data.y_values ?? data.y ?? (data.series?.length ? data.series.map((item: AnyRecord) => item.name) : [...new Set(sourceRows.map((row) => row[widget.y]))].sort((a, b) => Number(a) - Number(b)));
  const matrix: unknown[][] = data.z ?? data.matrix ?? (data.series?.length ? data.series.map((item: AnyRecord) => item.values) : ylabels.map((y) => xlabels.map((x) => {
    const matches = sourceRows.filter((row) => row[widget.x] === x && row[widget.y] === y).map((row) => number(row[widget.z ?? widget.size])).filter((v): v is number => v !== null);
    return matches.length ? matches.reduce((sum, v) => sum + v, 0) / matches.length : null;
  })));
  if (xlabels.length > 30 || ylabels.length > 30) throw new Error('3D bars support at most 30 distinct coordinates per axis. Filter the data or use 3D scatter.');
  const result: AnyRecord = { type: 'mesh3d', x: [], y: [], z: [], i: [], j: [], k: [], intensity: [], text: [], flatshading: true, showscale: true, colorscale: [[0, palette[1] ?? palette[0]], [1, palette[0]]], hovertemplate: '%{text}<extra></extra>', name: widget.y ?? 'Value' };
  const faces = [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]];
  matrix.forEach((row, yi) => row.forEach((value, xi) => {
    const z = number(value);
    if (z === null) return;
    const offset = result.x.length;
    const low = Math.min(0, z), high = Math.max(0, z);
    [[xi-.34,yi-.34,low],[xi+.34,yi-.34,low],[xi+.34,yi+.34,low],[xi-.34,yi+.34,low],[xi-.34,yi-.34,high],[xi+.34,yi-.34,high],[xi+.34,yi+.34,high],[xi-.34,yi+.34,high]].forEach(([x,y,h]) => {
      result.x.push(x); result.y.push(y); result.z.push(h); result.intensity.push(z);
      result.text.push(`${xlabels[xi] ?? xi} · ${ylabels[yi] ?? yi}: ${formatValue(z, widget)}`);
    });
    faces.forEach(([i,j,k]) => { result.i.push(offset+i); result.j.push(offset+j); result.k.push(offset+k); });
  }));
  return result;
}

/** Closed, extruded wedge meshes. Arc angles derive only from actual category totals. */
function meshPie(data: AnyRecord, widget: AnyRecord, palette: string[]): AnyRecord[] {
  const labels: unknown[] = data.labels ?? [];
  const numeric = values(data).map(number);
  if (numeric.some((value) => value !== null && value < 0)) throw new Error('3D pie charts require non-negative values. Choose a bar chart for signed data.');
  const total = numeric.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  if (!Number.isFinite(total) || total <= 0) throw new Error('A 3D pie chart requires a finite positive total.');
  const depth = Math.max(.02, Math.min(.75, number(widget.depth) ?? .2));
  const traces: AnyRecord[] = [];
  let start = 0;
  numeric.forEach((value, index) => {
    if (value === null || value <= 0) return;
    const sweep = value / total * Math.PI * 2;
    const segments = Math.max(2, Math.ceil(sweep / (Math.PI / 36)));
    const trace: AnyRecord = {
      type: 'mesh3d', name: String(labels[index] ?? ''), x: [0, 0], y: [0, 0], z: [0, depth],
      i: [], j: [], k: [], color: index === 0 && widget.color ? widget.color : palette[index % palette.length],
      opacity: Number(widget.opacity ?? 1), flatshading: false, showscale: false, showlegend: true,
      lighting: { ambient: .65, diffuse: .65, specular: .15, roughness: .65 },
      lightposition: { x: 100, y: 200, z: 300 },
      hovertemplate: '%{customdata[0]}<br>Value: %{customdata[1]:,.4~f}<br>Share: %{customdata[2]:.2f}%<extra></extra>',
      meta: { label: labels[index], value, share: value / total, start_angle: start, end_angle: start + sweep, depth },
    };
    for (let step = 0; step <= segments; step++) {
      const angle = start + sweep * step / segments;
      const x = Math.cos(angle), y = Math.sin(angle);
      trace.x.push(x, x); trace.y.push(y, y); trace.z.push(0, depth);
    }
    const face = (i: number, j: number, k: number) => { trace.i.push(i); trace.j.push(j); trace.k.push(k); };
    for (let step = 0; step < segments; step++) {
      const bottom = 2 + step * 2, top = bottom + 1;
      const nextBottom = bottom + 2, nextTop = top + 2;
      face(1, top, nextTop); // upper surface
      face(0, nextBottom, bottom); // lower surface
      face(bottom, nextBottom, nextTop); // outer curved wall
      face(bottom, nextTop, top);
    }
    const lastBottom = 2 + segments * 2, lastTop = lastBottom + 1;
    face(0, 2, 3); face(0, 3, 1); // starting radial wall
    face(0, 1, lastTop); face(0, lastTop, lastBottom); // ending radial wall
    trace.customdata = trace.x.map(() => [labels[index], value, value / total * 100]);
    traces.push(trace);
    if (widget.show_labels) {
      const middle = start + sweep / 2;
      traces.push({ type: 'scatter3d', mode: 'text', x: [Math.cos(middle) * .66], y: [Math.sin(middle) * .66], z: [depth + .012], text: [`${String(labels[index])}<br>${(value / total * 100).toFixed(1)}%`], customdata: [[labels[index], value, value / total * 100]], hoverinfo: 'skip', showlegend: false, textfont: { size: Number(widget.font_size ?? 11), color: widget.text_color ?? '#fff' } });
    }
    start += sweep;
  });
  return traces;
}

/** Translate the central analytics result to a genuine Plotly figure. No synthetic records. */
export function buildFigure(widget: AnyRecord, data: AnyRecord, theme: AnyRecord = {}): Figure {
  const type = widget.type ?? 'bar';
  const labels: unknown[] = data.labels ?? [];
  const series: AnyRecord[] = data.series?.length ? data.series : [];
  const palette: string[] = paletteFor(widget, theme);
  const accent = widget.color ?? palette[0];
  const textColor = widget.text_color ?? theme.text ?? '#344054';
  const dark = theme.mode === 'dark';
  const gridColor = dark ? 'rgba(148,163,184,.15)' : 'rgba(148,163,184,.18)';
  const font = { family: widget.font_family ?? theme.font ?? 'Inter, system-ui, sans-serif', color: textColor, size: Number(widget.font_size ?? 11) };
  const tickformat = widget.number_format === 'percent' ? ',.2f' : undefined;
  const axis = { gridcolor: gridColor, showgrid: truthy(widget.show_grid), zeroline: false, automargin: true, tickfont: font, linecolor: gridColor };
  const layout: AnyRecord = {
    autosize: true, margin: { l: 36, r: 18, t: 14, b: 32 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font, colorway: palette, hovermode: 'closest',
    showlegend: truthy(widget.show_legend, series.length > 1),
    legend: { orientation: widget.legend_position === 'right' ? 'v' : 'h', x: 0, y: widget.legend_position === 'top' ? 1.16 : -0.2, font, bgcolor: 'rgba(0,0,0,0)' },
    xaxis: { ...axis, title: { text: widget.x_label ?? '', font } },
    yaxis: { ...axis, tickformat, title: { text: widget.y_label ?? '', font } },
    hoverlabel: { bgcolor: theme.surface ?? (dark ? '#182234' : '#fff'), font, bordercolor: gridColor },
    uirevision: `${widget.id ?? 'chart'}-${type}-${widget.x ?? ''}-${widget.y ?? ''}`,
    transition: { duration: widget.animation === false || globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 180 },
  };
  const numericSeries = (item: AnyRecord) => (item.values ?? []).map(number);
  const traceStyle = (index: number) => ({ opacity: Number(widget.opacity ?? 1), marker: { color: index === 0 ? accent : palette[index % palette.length], line: { width: 0 } } });
  const showLabels = !!widget.show_labels;
  const bar = (orientation = 'v') => series.map((item, index) => ({
    type: 'bar', name: item.name, ...(orientation === 'h' ? { x: numericSeries(item), y: labels, orientation: 'h' } : { x: labels, y: numericSeries(item) }),
    ...traceStyle(index), text: showLabels ? numericSeries(item).map((v: unknown) => formatValue(v, widget)) : undefined,
    textposition: showLabels ? 'auto' : 'none', hovertemplate: orientation === 'h' ? '%{y}: %{x:,.4~f}<extra>%{fullData.name}</extra>' : '%{x}: %{y:,.4~f}<extra>%{fullData.name}</extra>',
  }));
  let traces: AnyRecord[];

  if (['bar','horizontal_bar','grouped_bar','stacked_bar','percent_bar','ranking'].includes(type)) {
    traces = bar(['horizontal_bar','ranking'].includes(type) ? 'h' : 'v');
    layout.barmode = ['stacked_bar','percent_bar'].includes(type) ? 'relative' : 'group';
    if (type === 'percent_bar') { layout.barnorm = 'percent'; layout.yaxis.ticksuffix = '%'; }
    if (type === 'ranking') layout.yaxis.autorange = 'reversed';
  } else if (['line','smooth_line','step_line','area','stacked_area','cumulative','moving_average','timeline'].includes(type)) {
    traces = series.map((item, index) => ({
      type: 'scatter', mode: `${widget.show_points || labels.length === 1 ? 'lines+markers' : 'lines'}${showLabels ? '+text' : ''}`, name: item.name,
      x: labels, y: numericSeries(item), line: { color: index === 0 ? accent : palette[index % palette.length], width: Number(widget.line_width ?? 2.5), shape: type === 'smooth_line' ? 'spline' : type === 'step_line' ? 'hv' : 'linear' },
      text: showLabels ? numericSeries(item).map((v: unknown) => formatValue(v, widget)) : undefined, textposition: 'top center',
      marker: { size: 5 }, fill: type === 'area' ? 'tozeroy' : undefined,
      stackgroup: type === 'stacked_area' ? 'stack' : undefined, opacity: Number(widget.opacity ?? 1),
      hovertemplate: '%{x}: %{y:,.4~f}<extra>%{fullData.name}</extra>',
    }));
    layout.hovermode = 'x unified';
  } else if (type === 'confidence_band') {
    const lower = data.bands?.lower ?? series.find((item) => item.name === widget.lower || item.name === 'lower')?.values;
    const upper = data.bands?.upper ?? series.find((item) => item.name === widget.upper || item.name === 'upper')?.values;
    const center = data.bands?.center ?? series.find((item) => item.name === widget.y || item.name === 'center')?.values ?? series[0]?.values;
    if (!lower?.length || !upper?.length || !center?.length) throw new Error('Choose actual center, lower and upper interval fields. Confidence intervals are never inferred.');
    traces = [
      { type: 'scatter', mode: 'lines', x: labels, y: lower, line: { width: 0 }, name: widget.lower ?? 'Lower bound', showlegend: false, hovertemplate: '%{x}: %{y:,.4~f}<extra>Provided lower bound</extra>' },
      { type: 'scatter', mode: 'lines', x: labels, y: upper, line: { width: 0 }, fill: 'tonexty', fillcolor: `rgba(${(/^#[\da-f]{6}$/i.test(accent) ? accent : '#4f46e5').slice(1).match(/.{2}/g)!.map((part: string) => parseInt(part, 16)).join(',')},.15)`, name: 'Provided interval', hovertemplate: '%{x}: %{y:,.4~f}<extra>Provided upper bound</extra>' },
      { type: 'scatter', mode: labels.length === 1 ? 'lines+markers' : 'lines', x: labels, y: center, name: widget.y ?? 'Center', line: { color: accent, width: 2.5 }, hovertemplate: '%{x}: %{y:,.4~f}<extra>Observed center</extra>' },
    ];
    layout.showlegend = truthy(widget.show_legend);
    layout.hovermode = 'x unified';
  } else if (type === 'pie3d') {
    traces = meshPie(data, widget, palette);
    const depth = Math.max(.02, Math.min(.75, number(widget.depth) ?? .2));
    layout.showlegend = truthy(widget.show_legend);
    layout.margin = { l: 0, r: 0, t: 0, b: 0 };
    layout.scene = {
      bgcolor: 'rgba(0,0,0,0)', dragmode: 'orbit',
      xaxis: { visible: false, range: [-1.1, 1.1] },
      yaxis: { visible: false, range: [-1.1, 1.1] },
      zaxis: { visible: false, range: [0, depth * 1.5] },
      aspectmode: 'manual', aspectratio: { x: 1, y: 1, z: depth * .9 },
      camera: { eye: { x: 1.4, y: -1.7, z: 1.5 } },
    };
  } else if (['pie','donut'].includes(type)) {
    const numeric = values(data).map(number);
    if (numeric.some((v) => v !== null && v < 0)) throw new Error('Pie charts require non-negative values. Choose a bar chart for signed data.');
    traces = [{ type: 'pie', labels, values: numeric, hole: type === 'pie' ? 0 : .66,
      sort: false, rotation: 0,
      marker: { colors: palette, line: { color: theme.surface ?? '#fff', width: 2 } },
      textinfo: showLabels ? 'label+percent' : 'none', hoverinfo: 'label+value+percent',
      hovertemplate: '%{label}: %{value:,.4~f}<extra></extra>',
    }];
    layout.showlegend = truthy(widget.show_legend, true);
    layout.margin = { l: 5, r: 5, t: 8, b: 8 };
  } else if (['treemap','sunburst'].includes(type)) {
    const hierarchy = data.hierarchy ?? {};
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    const tree: { ids: string[]; labels: string[]; parents: string[]; values: number[] } = { ids: [], labels: [], parents: [], values: [] };
    const walk = (items: AnyRecord[], parent: string) => items.forEach((node, index) => {
      const id = `${parent}/${index}:${node.name}`;
      const sum = (entry: AnyRecord): number => entry.children?.length ? entry.children.reduce((total: number, child: AnyRecord) => total + sum(child), 0) : number(entry.value) ?? 0;
      tree.ids.push(id); tree.labels.push(String(node.name)); tree.parents.push(parent); tree.values.push(sum(node));
      if (node.children?.length) walk(node.children, id);
    });
    if (Array.isArray(hierarchy)) walk(hierarchy, '');
    traces = [{ type, ids: tree.ids.length ? tree.ids : hierarchy.ids ?? (nodes.length ? nodes.map((node: AnyRecord) => node.id ?? node.name) : undefined), labels: tree.labels.length ? tree.labels : hierarchy.labels ?? (nodes.length ? nodes.map((node: AnyRecord) => node.label ?? node.name) : labels), parents: tree.parents.length ? tree.parents : hierarchy.parents ?? (nodes.length ? nodes.map((node: AnyRecord) => node.parent ?? '') : labels.map(() => '')),
      values: tree.values.length ? tree.values : hierarchy.values ?? (nodes.length ? nodes.map((node: AnyRecord) => node.value) : values(data)),
      branchvalues: hierarchy.branchvalues ?? 'total', marker: { colors: palette }, textinfo: showLabels ? 'label+value+percent entry' : 'label', hovertemplate: '%{label}: %{value:,.4~f}<extra></extra>',
    }];
    layout.margin = { l: 0, r: 0, t: 0, b: 0 };
  } else if (type === 'density') {
    if (!data.density?.x?.length || !data.density?.y?.length) throw new Error('Density curves require sufficient numerical observations.');
    traces = [{ type: 'scatter', mode: 'lines', x: data.density.x, y: data.density.y, line: { color: accent, width: 2.5, shape: 'spline' }, fill: 'tozeroy', name: widget.y ?? 'Density', hovertemplate: 'Value: %{x:,.4~f}<br>Density: %{y:.5f}<extra></extra>' }];
    layout.xaxis.title = { text: widget.y ?? '', font };
    layout.yaxis.title = { text: 'Probability density', font };
  } else if (type === 'histogram') {
    const samples = data.samples ?? data.values ?? fieldValues(data, widget.y ?? widget.x);
    traces = [{ type: 'histogram', x: samples.map(number).filter((v: unknown) => v !== null), marker: { color: accent, line: { color: theme.surface ?? '#fff', width: 1 } }, nbinsx: Number(widget.bins ?? 20), name: widget.y ?? widget.x }];
    layout.yaxis.title = { text: 'Frequency', font };
    layout.bargap = .04;
  } else if (['box','violin'].includes(type)) {
    const groups = data.groups ?? (widget.x ? (data.rows ?? []).reduce((map: AnyRecord, row: AnyRecord) => { const name = String(row[widget.x] ?? '(Missing)'); (map[name] ??= []).push(row[widget.y]); return map; }, {}) : null);
    traces = groups ? Object.entries(groups).map(([name,samples], index) => ({ type, name, y: samples, ...traceStyle(index), boxpoints: 'outliers', box: { visible: true }, meanline: { visible: true } })) : [{ type, y: data.samples ?? data.values ?? fieldValues(data, widget.y ?? widget.x), name: widget.y ?? widget.x, ...traceStyle(0), boxpoints: 'outliers', box: { visible: true }, meanline: { visible: true } }];
    layout.showlegend = false;
  } else if (type === 'regression') {
    const rows: AnyRecord[] = data.rows ?? [];
    if (!data.regression?.x?.length || !data.regression?.y?.length) throw new Error('A regression trend requires two numerical fields with varying X values.');
    traces = [{ type: 'scatter', mode: 'markers', x: rows.map((row) => row[widget.x]), y: rows.map((row) => row[widget.y]), marker: { color: accent, size: 6, opacity: .55 }, name: 'Observations' }, { type: 'scatter', mode: 'lines', x: data.regression.x, y: data.regression.y, line: { color: palette[1] ?? accent, width: 2.5 }, name: `OLS trend · R² ${Number(data.regression.r_squared).toFixed(3)}`, hovertemplate: '%{x:,.4~f}: %{y:,.4~f}<extra>OLS fitted value</extra>' }];
    layout.showlegend = truthy(widget.show_legend);
  } else if (['scatter','bubble','scatter3d'].includes(type)) {
    const rows: AnyRecord[] = data.rows ?? [];
    const dimensions = data.points ?? {};
    const x = dimensions.x ?? data.x ?? rows.map((row) => row[widget.x]);
    const y = dimensions.y ?? data.y ?? rows.map((row) => row[widget.y]);
    const z = dimensions.z ?? data.z ?? rows.map((row) => row[widget.z ?? widget.size]);
    const sizes = dimensions.size ?? rows.map((row) => row[widget.size ?? widget.z]);
    const numericSizes = sizes.map(number).map((value: number | null) => Math.max(0, value ?? 0));
    const maxSize = Math.max(1, ...numericSizes);
    traces = [{ type: type === 'scatter3d' ? 'scatter3d' : 'scatter', mode: 'markers', x, y,
      ...(type === 'scatter3d' ? { z } : {}),
      text: rows.map((row) => widget.series ? String(row[widget.series] ?? '') : ''),
      marker: { color: widget.series ? rows.map((row) => row[widget.series]).map((v,_,all) => palette[all.indexOf(v) % palette.length]) : accent, opacity: Number(widget.opacity ?? .75), size: type === 'bubble' ? numericSizes.map((value: number) => 6 + Math.sqrt(value/maxSize)*32) : 6, line: { width: .5, color: theme.surface ?? '#fff' } },
      name: widget.y,
    }];
    layout.showlegend = false;
    if (type === 'scatter3d') layout.scene = { xaxis: { ...axis, title: widget.x }, yaxis: { ...axis, title: widget.y }, zaxis: { ...axis, title: widget.z }, bgcolor: 'rgba(0,0,0,0)' };
  } else if (type === 'heatmap') {
    const names = data.fields ?? data.columns ?? labels;
    traces = [{ type: 'heatmap', z: data.matrix ?? data.z, x: data.x ?? names, y: data.y ?? names, zmin: -1, zmax: 1, zmid: 0, colorscale: [[0,'#ef4444'],[.5,dark?'#243047':'#f8fafc'],[1,accent]], hovertemplate: '%{x} × %{y}: %{z:.3f}<extra></extra>', texttemplate: showLabels ? '%{z:.2f}' : undefined, colorbar: { thickness: 10 } }];
    layout.margin.r = 40;
  } else if (type === 'pareto') {
    const numeric = values(data).map((v) => number(v) ?? 0), total = numeric.reduce((a,b) => a+b,0);
    let current = 0;
    traces = [{ type:'bar',x:labels,y:numeric,marker:{color:accent},name:series[0]?.name??'Value' }, { type:'scatter',mode:'lines+markers',x:labels,y:data.cumulative_percent ?? numeric.map((value) => { current += value; return total === 0 ? 0 : current/total*100; }),name:'Cumulative share',yaxis:'y2',line:{color:palette[1]??'#f59e0b',width:2} }];
    layout.yaxis2 = { ...axis, overlaying:'y',side:'right',range:[0,105],ticksuffix:'%',showgrid:false };
    layout.margin.r=45;
  } else if (type === 'waterfall') {
    traces = [{ type:'waterfall',x:labels,y:values(data).map(number),measure:labels.map(()=>'relative'),connector:{line:{color:gridColor}},increasing:{marker:{color:accent}},decreasing:{marker:{color:'#ef4444'}},textposition:showLabels?'outside':'none' }];
  } else if (type === 'funnel') {
    traces = [{ type:'funnel',y:labels,x:values(data).map(number),textinfo:showLabels?'value+percent initial':'value',marker:{color:palette},connector:{line:{color:gridColor}} }];
    layout.margin.l=65;
  } else if (['gauge','bullet','progress'].includes(type)) {
    const value = number(data.value) ?? number(values(data)[0]);
    const target = number(widget.target ?? data.target);
    if (value === null) throw new Error('No numerical values are available for this performance chart.');
    if (target === null || target <= 0) throw new Error('Set a positive target to render this performance chart.');
    traces = [{ type:'indicator',mode:'number+gauge',value:value??0,number:{font:{...font,size:32},suffix:widget.suffix??'',prefix:widget.prefix??''},gauge:{shape:type==='gauge'?'angular':'bullet',axis:{range:[0,Math.max(target,(value??0)*1.05)],tickfont:font},bar:{color:accent},bgcolor:gridColor,borderwidth:0,threshold:{value:target,line:{color:textColor,width:3},thickness:.8}},domain:{x:[0.05,.95],y:[.08,.95]} }];
    layout.margin={l:25,r:25,t:15,b:15};
  } else if (type === 'radar') {
    traces=series.map((item,index)=>({type:'scatterpolar',r:[...numericSeries(item),numericSeries(item)[0]],theta:[...labels,labels[0]],fill:'toself',name:item.name,line:{color:index===0?accent:palette[index%palette.length],width:2},opacity:Number(widget.opacity??.7)}));
    layout.polar={bgcolor:'rgba(0,0,0,0)',radialaxis:{...axis,visible:true},angularaxis:{...axis}};
    layout.margin={l:35,r:35,t:20,b:25};
  } else if (type === 'sankey') {
    const nodes: AnyRecord[] = data.nodes ?? [];
    const nodeLabels: string[] = data.node_labels ?? nodes.map((node: AnyRecord | string) => typeof node==='string'?node:node.label??node.name??node.id);
    const links: AnyRecord[] = Array.isArray(data.links) ? data.links : [];
    const indexFor=(value: unknown)=>typeof value==='number'?value:nodes.findIndex((node: AnyRecord | string)=>typeof node==='string'?node===value:(node.id??node.name)===value);
    traces=[{type:'sankey',orientation:'h',node:{label:nodeLabels,color:nodeLabels.map((_,i)=>palette[i%palette.length]),pad:15,thickness:16,line:{width:0}},link:{source:links.map((link)=>indexFor(link.source)),target:links.map((link)=>indexFor(link.target)),value:links.map((link)=>number(link.value)),color:dark?'rgba(148,163,184,.22)':'rgba(99,102,241,.14)'}}];
    layout.margin={l:10,r:10,t:10,b:10};
  } else if (type === 'map') {
    const rows: AnyRecord[] = data.rows ?? [];
    const weight = widget.z ?? widget.size;
    const magnitudes = rows.map((row) => Math.abs(number(row[weight]) ?? 0));
    const maxWeight = Math.max(1, ...magnitudes);
    traces = [{ type: 'scattergeo', mode: 'markers', lon: rows.map((row) => row[widget.x]), lat: rows.map((row) => row[widget.y]),
      customdata: rows.map((row) => [row[widget.x], row[widget.y], widget.series ? row[widget.series] : '', weight ? row[weight] : null]),
      marker: { color: accent, size: weight ? magnitudes.map((value) => 6 + Math.sqrt(value / maxWeight) * 20) : 10, opacity: .8, line: { color: theme.surface ?? '#fff', width: 1 } },
      hovertemplate: `${widget.series ? '%{customdata[2]}<br>' : ''}Longitude: %{lon:.4f}<br>Latitude: %{lat:.4f}${weight ? '<br>Value: %{customdata[3]:,.4~f}' : ''}<extra></extra>`,
    }];
    layout.geo = { resolution: 110, projection: { type: 'natural earth' }, showframe: false, showcoastlines: false, showland: true, showcountries: true,
      landcolor: dark ? '#28364c' : '#e6ebf3', countrycolor: dark ? '#41516b' : '#fff', showocean: true, oceancolor: dark ? '#152033' : '#f3f7fc', bgcolor: 'rgba(0,0,0,0)',
    };
    layout.showlegend = false;
    layout.margin = { l: 0, r: 0, t: 0, b: 0 };
    // Plotly's geo fitbounds path calls Cartesian axis matching before async
    // topology initialization finishes. A world view is stable and preserves
    // exact uploaded coordinates; visitors can zoom and pan normally.
    delete layout.xaxis;
    delete layout.yaxis;
    layout.transition = { duration: 0 };
  } else if (type === 'calendar') {
    const dates = labels.map((label) => new Date(String(label)));
    const validDates=dates.filter((date)=>Number.isFinite(date.getTime()));
    if (!validDates.length) throw new Error('Calendar heatmaps require valid dates.');
    const start=new Date(Math.min(...validDates.map((date)=>date.getTime()))); start.setUTCHours(0,0,0,0);start.setUTCDate(start.getUTCDate()-((start.getUTCDay()+6)%7));
    const end=Math.max(...validDates.map((date)=>date.getTime()));
    const weeks=Math.floor((end-start.getTime())/(7*86400000))+1;
    const z=Array.from({length:7},()=>Array.from({length:weeks},()=>null as number|null));
    const custom=Array.from({length:7},()=>Array.from({length:weeks},()=>''));
    dates.forEach((date,index)=>{if(!Number.isFinite(date.getTime()))return;const week=Math.floor((date.getTime()-start.getTime())/(7*86400000));const day=(date.getUTCDay()+6)%7;z[day][week]=number(values(data)[index]);custom[day][week]=date.toISOString().slice(0,10);});
    traces=[{type:'heatmap',z,x:Array.from({length:weeks},(_,i)=>new Date(start.getTime()+i*7*86400000).toISOString().slice(0,10)),y:['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],customdata:custom,colorscale:[[0,dark?'#1e293b':'#eef2ff'],[1,accent]],xgap:3,ygap:3,hoverongaps:false,hovertemplate:'%{customdata}: %{z:,.4~f}<extra></extra>',colorbar:{thickness:10}}];
    layout.yaxis.autorange='reversed';layout.margin.r=40;
  } else if (type === 'gantt') {
    const rows: AnyRecord[] = data.rows ?? [];
    traces=[{type:'bar',orientation:'h',base:rows.map((row)=>row.start),x:rows.map((row)=>row.duration),y:rows.map((row)=>row.task??''),marker:{color:accent},customdata:rows.map((row)=>`${row.start} → ${row.end}`),hovertemplate:'%{y}<br>%{customdata}<extra></extra>'}];
    layout.xaxis.type='date';layout.yaxis.autorange='reversed';layout.barmode='overlay';
  } else if (['surface3d','bar3d'].includes(type)) {
    const x=data.x_values??data.x??(type==='bar3d'?[...new Set((data.rows??[]).map((row:AnyRecord)=>row[widget.x]))].sort((a,b)=>Number(a)-Number(b)):labels), y=data.y_values??data.y??(type==='bar3d'?[...new Set((data.rows??[]).map((row:AnyRecord)=>row[widget.y]))].sort((a,b)=>Number(a)-Number(b)):series.map((item)=>item.name)), z=data.z??data.matrix??series.map((item)=>item.values);
    traces=type==='surface3d'?[{type:'surface',x,y,z,colorscale:[[0,palette[1]??'#06b6d4'],[1,accent]],colorbar:{thickness:10}}]:[meshBars(data,widget,palette)];
    layout.scene={bgcolor:'rgba(0,0,0,0)',xaxis:{...axis,title:widget.x,tickvals:type==='bar3d'?x.map((_:unknown,i:number)=>i):undefined,ticktext:type==='bar3d'?x:undefined},yaxis:{...axis,title:widget.series??widget.y,tickvals:type==='bar3d'?y.map((_:unknown,i:number)=>i):undefined,ticktext:type==='bar3d'?y:undefined},zaxis:{...axis,title:widget.z??widget.y}};
    layout.margin={l:0,r:20,t:0,b:0};
  } else {
    throw new Error(`The ${chartName(type)} visualization is not supported by this renderer.`);
  }
  // Plotly's default autoscale for one date point spans milliseconds. Use a real bucket.
  if (!['horizontal_bar','ranking','funnel','pie','donut','pie3d','map','sankey','scatter3d','surface3d','bar3d','radar','heatmap','calendar','gantt'].includes(type) && labels.length && labels.every((value) => typeof value === 'string' && /^\d{4}-\d{2}(?:-\d{2}(?:[T ].*)?)?$/.test(value))) {
    const granularity = widget.granularity ?? widget.time_granularity;
    layout.xaxis.type = 'date';
    layout.xaxis.tickformat = granularity === 'hour' ? '%H:%M<br>%d %b' : granularity === 'day' || granularity === 'week' ? '%d %b<br>%Y' : '%b<br>%Y';
    layout.xaxis.nticks = 5;
    layout.xaxis.tickangle = 0;
    if (labels.length === 1) {
      const point = new Date(String(labels[0]));
      if (Number.isFinite(point.getTime())) {
        const span = granularity === 'hour' ? 3600000 : granularity === 'day' ? 86400000 : granularity === 'week' ? 7 * 86400000 : 31 * 86400000;
        layout.xaxis.range = [new Date(point.getTime() - span / 2).toISOString(), new Date(point.getTime() + span / 2).toISOString()];
        layout.xaxis.tickvals = [point.toISOString()];
        layout.xaxis.ticktext = [point.toLocaleDateString('en-US', { month: 'short', ...(granularity === 'day' || granularity === 'week' ? { day: 'numeric' } : {}), year: 'numeric', timeZone: 'UTC' })];
      }
    }
  }
  return { data: traces, layout };
}

function downloadCsv(widget: AnyRecord, data: AnyRecord) {
  const rows: AnyRecord[] = data.rows?.length ? data.rows : (data.labels ?? []).map((label: unknown,index: number)=>Object.fromEntries([[widget.x??'Category',label],...(data.series??[]).map((series: AnyRecord)=>[series.name,series.values[index]])]));
  if (!rows.length && data.value !== undefined) rows.push({ Metric: widget.title ?? 'Metric', Value: data.value });
  const columns: string[] = data.columns?.length ? data.columns : Array.from(new Set(rows.flatMap((row)=>Object.keys(row))));
  const cell = (value: unknown) => {
    let text = value === null || value === undefined ? '' : typeof value==='object' ? JSON.stringify(value) : String(value);
    if (typeof value==='string' && /^[\s]*[=+\-@\t\r]/.test(text)) text=`'${text}`;
    return `"${text.replaceAll('"','""')}"`;
  };
  const csv='\uFEFF'+[columns.map(cell).join(','),...rows.map((row)=>columns.map((column)=>cell(row[column])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`${String(widget.title??'chart').replace(/[^a-z0-9_-]/gi,'_')}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function DataTable({ widget, data, onSelect }: ChartProps) {
  const spec=widget as AnyRecord, result=data as AnyRecord;
  const [search,setSearch]=useState(''),[sort,setSort]=useState<string>(''),[descending,setDescending]=useState(false),[page,setPage]=useState(0);
  const rows: AnyRecord[]=result.rows??[];
  const columns: string[]=result.columns??Array.from(new Set(rows.flatMap((row)=>Object.keys(row))));
  const filtered=useMemo(()=>{
    const subset=rows.filter((row)=>!search||columns.some((column)=>String(row[column]??'').toLowerCase().includes(search.toLowerCase())));
    if(sort)subset.sort((a,b)=>{const av=a[sort],bv=b[sort],an=number(av),bn=number(bv);const order=an!==null&&bn!==null?an-bn:String(av??'').localeCompare(String(bv??''),undefined,{numeric:true});return descending?-order:order;});
    return subset;
  },[rows,columns,search,sort,descending]);
  useEffect(()=>setPage(0),[search,sort,descending,rows]);
  const pageSize=10,pageCount=Math.max(1,Math.ceil(filtered.length/pageSize));
  const currentPage=Math.min(page,pageCount-1);
  return <div style={{display:'flex',flexDirection:'column',height:'100%',minHeight:0,gap:8,fontSize:12}}>
    <div style={{display:'flex',alignItems:'center',gap:6,padding:'0 4px'}}><Search size={13}/><input aria-label="Search table" placeholder="Search records…" value={search} onChange={(event)=>setSearch(event.target.value)} style={{font:'inherit',background:'transparent',color:'inherit',border:0,outline:'none',width:'100%',padding:4}}/><button type="button" title="Export visible chart data as CSV" aria-label="Export table CSV" onClick={()=>downloadCsv(spec,{...result,rows:filtered})} style={iconButton}><Download size={13}/></button></div>
    <div style={{overflow:'auto',flex:1,minHeight:0}}><table style={{width:'100%',borderCollapse:'collapse',whiteSpace:'nowrap',fontSize:12}}><thead><tr>{columns.map((column)=><th key={column} scope="col" style={{position:'sticky',top:0,textAlign:'left',padding:'9px 12px',background:'var(--surface,#f8fafc)',borderBottom:'1px solid rgba(148,163,184,.2)',fontWeight:600}}><button type="button" onClick={()=>{if(sort===column)setDescending(!descending);else{setSort(column);setDescending(false);}}} style={{...iconButton,width:'100%',justifyContent:'space-between',gap:8,whiteSpace:'nowrap',fontWeight:600}}>{column}<ArrowUpDown size={11} aria-hidden="true"/></button></th>)}</tr></thead><tbody>{filtered.slice(currentPage*pageSize,(currentPage+1)*pageSize).map((row,index)=><tr key={index}>{columns.map((column)=><td key={column} onClick={()=>onSelect?.(column,row[column])} style={{padding:'9px 12px',borderBottom:'1px solid rgba(148,163,184,.12)',cursor:onSelect?'pointer':undefined,background:spec.conditional_formatting&&number(row[column])!==null?`rgba(79,70,229,${Math.min(.2,Math.abs(number(row[column])??0)/1000)})`:undefined}}>{typeof row[column]==='number'?formatValue(row[column],spec):row[column]===null||row[column]===undefined?'—':typeof row[column]==='object'?JSON.stringify(row[column]):String(row[column])}</td>)}</tr>)}</tbody></table>{!filtered.length&&<div style={{padding:24,textAlign:'center',opacity:.6}}>No matching records</div>}</div>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'0 5px',opacity:.75,fontSize:11}}><span>{filtered.length.toLocaleString()} shown{result.total_rows>rows.length?` of ${result.total_rows.toLocaleString()}`:''}</span><span style={{display:'flex',alignItems:'center',gap:8}}><button aria-label="Previous table page" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)} style={iconButton}><ChevronLeft size={13}/></button>{currentPage+1} / {pageCount}<button aria-label="Next table page" disabled={currentPage+1>=pageCount} onClick={()=>setPage(currentPage+1)} style={iconButton}><ChevronRight size={13}/></button></span></div>
  </div>;
}

function Kpi({ widget, data, theme }: ChartProps) {
  const spec=widget as AnyRecord,result=data as AnyRecord;
  const value=number(result.value),target=number(spec.target??result.target),comparison=number(result.previous??result.comparison??result.previous_value);
  const change=number(result.change??result.growth??result.change_percent??result.delta_percent)??(comparison!==null&&comparison!==0&&value!==null?(value-comparison)/Math.abs(comparison)*100:null);
  const accent=spec.color??(theme as AnyRecord)?.accent??DEFAULT_PALETTE[0];
  const spark: number[]=(result.sparkline??result.trend??result.series?.[0]?.values??[]).map((item:unknown)=>number(typeof item==='object'&&item!==null?(item as AnyRecord).value:item)).filter((v: number|null)=>v!==null);
  const low=spark.length?Math.min(...spark):0,high=spark.length?Math.max(...spark):0;
  const points=spark.map((item,index)=>`${spark.length===1?0:index/(spark.length-1)*220},${45-(high===low?.5:(item-low)/(high-low))*38}`).join(' ');
  return <div style={{height:'100%',display:'flex',flexDirection:'column',justifyContent:'center',padding:'0 8px',minHeight:0,gap:8}}>
    <div style={{fontSize:Math.max(24,Number(spec.value_font_size??spec.font_size??36)),fontWeight:650,letterSpacing:'-.045em',lineHeight:1.15,color:spec.text_color??'inherit',fontVariantNumeric:'tabular-nums'}}>{formatValue(result.value,spec)}</div>
    {spec.description&&<div style={{fontSize:12,opacity:.65}}>{spec.description}</div>}
    {change!==null&&<div style={{fontSize:12,color:(spec.positive_direction==='down'?change<=0:change>=0)?'#059669':'#dc2626',fontWeight:600}}>{change>=0?'↗':'↘'} {Math.abs(change).toFixed(1)}% <span style={{opacity:.6,fontWeight:400}}>vs. comparison</span></div>}
    {target!==null&&target>0&&value!==null&&<div><div style={{display:'flex',justifyContent:'space-between',fontSize:11,opacity:.65,marginBottom:5}}><span>{(value/target*100).toFixed(1)}% of target</span><span>{formatValue(target,spec)}</span></div><div role="meter" aria-label="Progress to target" aria-valuenow={value} aria-valuemin={0} aria-valuemax={target} style={{height:5,borderRadius:8,background:'rgba(148,163,184,.15)',overflow:'hidden'}}><div style={{height:'100%',width:`${Math.max(0,Math.min(100,value/target*100))}%`,background:accent,borderRadius:8}}/></div></div>}
    {spark.length>1&&<svg viewBox="0 0 220 50" aria-label="Metric trend" role="img" style={{width:'100%',height:38,flexShrink:1}} preserveAspectRatio="none"><polyline fill="none" stroke={accent} strokeWidth="2" strokeLinejoin="round" points={points}/></svg>}
    <div style={{fontSize:10,opacity:.4}}>{result.filtered_count!==undefined?`${Number(result.filtered_count).toLocaleString()} records · `:''}{spec.formula?'Calculated metric':String(spec.aggregation??'sum').replaceAll('_',' ')}</div>
  </div>;
}

/** A true semicircle: every arc is sized from its actual share, without padding slices. */
function SemiDonut({ widget, data, theme, onSelect }: ChartProps) {
  const spec = widget as AnyRecord, result = data as AnyRecord;
  const [hidden, setHidden] = useState<Set<number>>(new Set());
  useEffect(() => setHidden(new Set()), [data]);
  const palette = paletteFor(spec, (theme ?? {}) as AnyRecord);
  const measures = values(result).map(number);
  const negative = measures.some((value) => value !== null && value < 0);
  const total = measures.reduce<number>((sum, value, index) => sum + (hidden.has(index) ? 0 : value ?? 0), 0);
  let currentAngle = Math.PI;
  const arcs = measures.map((value, index) => {
    if (hidden.has(index) || value === null || value <= 0 || total <= 0) return null;
    const from = currentAngle, to = from - value / total * Math.PI;
    currentAngle = to;
    const point = (radius: number, angle: number) => `${180 + radius * Math.cos(angle)},${170 - radius * Math.sin(angle)}`;
    const path = `M${point(145, from)} A145,145 0 0,1 ${point(145, to)} L${point(97, to)} A97,97 0 0,0 ${point(97, from)} Z`;
    return <path key={index} d={path} fill={palette[index % palette.length]} stroke={(theme as AnyRecord)?.surface ?? '#fff'} strokeWidth={2} onClick={() => onSelect?.(spec.x, result.labels[index])} role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect?.(spec.x, result.labels[index]); } }} style={{ cursor: onSelect ? 'pointer' : 'default' }} aria-label={`${result.labels[index]}: ${formatValue(value, spec)}, ${(value / total * 100).toFixed(1)} percent`}><title>{result.labels[index]}: {formatValue(value, spec)} ({(value / total * 100).toFixed(1)}%)</title></path>;
  });
  if (negative) return <ChartMessage message="Pie charts require non-negative values. Choose a bar chart for signed data."/>;
  if (!measures.some((value) => value !== null && value > 0)) return <ChartMessage message="No positive contributions to display."/>;
  return <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
    <svg viewBox="0 0 360 190" role="img" aria-label="Semi-doughnut contribution chart" style={{ width: '100%', minHeight: 0, flex: 1, overflow: 'visible' }}>
      {arcs}<text x={180} y={140} textAnchor="middle" fill={spec.text_color ?? (theme as AnyRecord)?.text ?? '#344054'} fontFamily={spec.font_family ?? (theme as AnyRecord)?.font ?? 'system-ui'} fontSize={24} fontWeight={600}>{formatValue(total, spec)}</text><text x={180} y={160} textAnchor="middle" fill={spec.text_color ?? (theme as AnyRecord)?.text ?? '#64748b'} fontSize={11}>{total ? 'Total contribution' : 'Restore a category using the legend'}</text>
    </svg>
    {truthy(spec.show_legend) && <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '4px 12px', fontSize: 10, maxHeight: 70, overflowY: 'auto', padding: '0 8px 15px' }}>{(result.labels ?? []).map((label: unknown, index: number) => <button key={index} type="button" aria-pressed={!hidden.has(index)} onClick={() => setHidden((previous) => { const next = new Set(previous); if (next.has(index)) next.delete(index); else next.add(index); return next; })} style={{ ...iconButton, gap: 4, opacity: hidden.has(index) ? .35 : 1 }}><span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 2, background: palette[index % palette.length] }}/>{String(label)}</button>)}</div>}
  </div>;
}

export function buildChordGeometry(data: AnyRecord) {
  const nodes: AnyRecord[] = (data.nodes ?? []).map((node: AnyRecord | string, index: number) => ({ id: typeof node === 'string' ? index : node.id ?? index, name: typeof node === 'string' ? node : node.name ?? node.label ?? '', degree: 0, start: 0, end: 0, cursor: 0 }));
  const resolve = (id: unknown) => nodes.findIndex((node) => node.id === id);
  const links = (data.links ?? []).map((link: AnyRecord) => ({ source: resolve(link.source), target: resolve(link.target), value: number(link.value) }));
  if (links.some((link: AnyRecord) => link.source < 0 || link.target < 0 || link.value === null || link.value < 0)) throw new Error('Chord ribbons require valid source, destination and non-negative weights.');
  const positive = links.filter((link: AnyRecord) => link.value > 0);
  positive.forEach((link: AnyRecord) => { nodes[link.source].degree += link.value; nodes[link.target].degree += link.value; });
  const total = positive.reduce((sum: number, link: AnyRecord) => sum + link.value, 0);
  if (!Number.isFinite(total) || total <= 0) throw new Error('No positive relationship weights to display.');
  const shown = nodes.filter((node) => node.degree > 0);
  const gap = Math.min(.045, Math.PI / shown.length * .2);
  const scale = (2 * Math.PI - gap * shown.length) / (2 * total);
  let angle = -Math.PI / 2;
  shown.forEach((node) => { node.start = node.cursor = angle; node.end = angle + node.degree * scale; angle = node.end + gap; });
  const point = (radius: number, angle: number) => `${Math.cos(angle) * radius},${Math.sin(angle) * radius}`;
  const sector = (start: number, end: number) => `M${point(153,start)} A153,153 0 ${end-start>Math.PI?1:0},1 ${point(153,end)} L${point(139,end)} A139,139 0 ${end-start>Math.PI?1:0},0 ${point(139,start)} Z`;
  const arcs = shown.map((node) => ({ ...node, path: sector(node.start, node.end) }));
  const ribbons = positive.map((link: AnyRecord) => {
    const source = nodes[link.source], target = nodes[link.target];
    const sourceStart = source.cursor, sourceEnd = sourceStart + link.value * scale; source.cursor = sourceEnd;
    const targetStart = target.cursor, targetEnd = targetStart + link.value * scale; target.cursor = targetEnd;
    const path = `M${point(136,sourceStart)} A136,136 0 ${sourceEnd-sourceStart>Math.PI?1:0},1 ${point(136,sourceEnd)} Q0,0 ${point(136,targetStart)} A136,136 0 ${targetEnd-targetStart>Math.PI?1:0},1 ${point(136,targetEnd)} Q0,0 ${point(136,sourceStart)} Z`;
    return { ...link, sourceName: source.name, targetName: target.name, sourceStart, sourceEnd, targetStart, targetEnd, path };
  });
  return { arcs, ribbons, total, scale };
}

function Chord({ widget, data, theme, onSelect }: ChartProps) {
  const spec=widget as AnyRecord;
  const palette=paletteFor(spec,(theme??{}) as AnyRecord);
  const [active,setActive]=useState<number|null>(null);
  let geometry: ReturnType<typeof buildChordGeometry>;
  try { geometry=buildChordGeometry(data); } catch (failure) { return <ChartMessage message={failure instanceof Error?failure.message:'Unable to draw relationships.'}/>; }
  return <div style={{height:'100%',display:'flex',flexDirection:'column',minHeight:0}}>
    <svg viewBox="-190 -190 380 380" role="img" aria-label="Weighted category relationship chord diagram" style={{width:'100%',minHeight:0,flex:1}}>
      {geometry.ribbons.map((ribbon:AnyRecord,index:number)=><path key={index} d={ribbon.path} fill={palette[ribbon.source%palette.length]} opacity={active===null?.5:active===index?.8:.1} stroke={(theme as AnyRecord)?.surface??'#fff'} strokeWidth={.5} onMouseEnter={()=>setActive(index)} onMouseLeave={()=>setActive(null)} onFocus={()=>setActive(index)} onBlur={()=>setActive(null)} role={onSelect?'button':undefined} tabIndex={onSelect?0:undefined} aria-label={`${ribbon.sourceName} to ${ribbon.targetName}: ${formatValue(ribbon.value,spec)}`} onClick={()=>onSelect?.(spec.x,ribbon.sourceName,[{field:spec.series,value:ribbon.targetName}])} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();onSelect?.(spec.x,ribbon.sourceName,[{field:spec.series,value:ribbon.targetName}]);}}} style={{cursor:onSelect?'pointer':'default'}}><title>{ribbon.sourceName} → {ribbon.targetName}: {formatValue(ribbon.value,spec)}</title></path>)}
      {geometry.arcs.map((arc:AnyRecord,index:number)=>{const middle=(arc.start+arc.end)/2;return <g key={arc.id}><path d={arc.path} fill={palette[index%palette.length]}><title>{arc.name}: {formatValue(arc.degree,spec)} total incident weight</title></path>{spec.show_labels&&<text x={Math.cos(middle)*167} y={Math.sin(middle)*167} textAnchor={Math.cos(middle)>.1?'start':Math.cos(middle)<-.1?'end':'middle'} dominantBaseline="central" fontSize={10} fill={spec.text_color??(theme as AnyRecord)?.text??'#344054'}>{String(arc.name).length>15?String(arc.name).slice(0,14)+'…':arc.name}</text>}</g>;})}
    </svg>
    {truthy(spec.show_legend)&&<div style={{display:'flex',flexWrap:'wrap',justifyContent:'center',gap:'3px 12px',fontSize:10,maxHeight:60,overflowY:'auto',paddingBottom:15}}>{geometry.arcs.map((arc:AnyRecord,index:number)=><span key={arc.id} style={{display:'flex',alignItems:'center',gap:4}}><span style={{width:7,height:7,borderRadius:2,background:palette[index%palette.length]}}/>{arc.name}</span>)}</div>}
  </div>;
}

const iconButton: React.CSSProperties={display:'inline-flex',alignItems:'center',justifyContent:'center',padding:4,border:0,borderRadius:4,background:'transparent',color:'inherit',cursor:'pointer',font:'inherit'};

class ChartBoundary extends Component<{children:React.ReactNode;reset:string},{error:string|null}> {
  state={error:null as string|null};
  static getDerivedStateFromError(error:Error){return {error:error.message};}
  componentDidUpdate(previous:{reset:string}){if(previous.reset!==this.props.reset&&this.state.error)this.setState({error:null});}
  render(){return this.state.error?<ChartMessage message={this.state.error}/>:this.props.children;}
}
function ChartMessage({message}:{message:string}){return <div role="status" style={{height:'100%',display:'flex',alignItems:'center',justifyContent:'center',textAlign:'center',padding:20,fontSize:12,lineHeight:1.6,color:'var(--muted,#64748b)'}}>{message}</div>;}

export default function Chart(props:ChartProps) {
  const {widget,data,theme={},onSelect}=props;
  const spec=widget as AnyRecord,result=data as AnyRecord;
  const container=useRef<HTMLDivElement>(null),graph=useRef<any>(null);
  const [dimensions,setDimensions]=useState({width:0,height:0}),[error,setError]=useState<string|null>(null);
  useEffect(()=>{const element=container.current;if(!element)return;const resize=new ResizeObserver(([entry])=>{setDimensions({width:Math.floor(entry.contentRect.width),height:Math.floor(entry.contentRect.height)});});resize.observe(element);return()=>resize.disconnect();},[]);
  useEffect(()=>setError(null),[spec.type,data]);
  const figure=useMemo(()=>{if(TABLE_TYPES.has(spec.type)||spec.type==='kpi'||spec.type==='semi_donut'||spec.type==='chord')return null;try{return buildFigure(spec,result,theme as AnyRecord);}catch(failure){return {error:failure instanceof Error?failure.message:'Unable to configure this chart.'};}},[widget,data,theme]);
  const hasRecords=(result.filtered_count??result.filtered_rows??result.total_rows??result.row_count)!==0;
  const empty=!hasRecords||(spec.type!=='kpi'&&!TABLE_TYPES.has(spec.type)&&!(result.labels?.length||result.rows?.length||result.nodes?.length||result.matrix?.length||result.z?.length||(result.value!==undefined&&result.value!==null)||result.samples?.length));
  const exportSvg=async()=>{try{if(spec.type==='semi_donut'||spec.type==='chord'){const svg=container.current?.querySelector('svg[role="img"]');if(!svg)throw new Error('Chart is not ready.');const clone=svg.cloneNode(true) as SVGSVGElement;clone.setAttribute('xmlns','http://www.w3.org/2000/svg');const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`${String(spec.title??'chart').replace(/[^a-z0-9_-]/gi,'_')}.svg`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}if(!graph.current)throw new Error('Chart is not ready.');const plotly=await import('plotly.js-dist-min');await plotly.default.downloadImage(graph.current,{format:'svg',filename:String(spec.title??'chart'),width:dimensions.width||800,height:dimensions.height||450});}catch{setError('The chart could not be exported. Try the PNG download in the chart toolbar.');}};
  const fullscreen=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await container.current?.requestFullscreen();}catch{setError('Fullscreen is unavailable in this browser.');}};
  return <div ref={container} className="chart-renderer" style={{position:'relative',height:'100%',width:'100%',minHeight:0,minWidth:0,background:spec.background??'transparent',color:spec.text_color??(theme as AnyRecord).text??'inherit',fontFamily:spec.font_family??(theme as AnyRecord).font}}>
    {TABLE_TYPES.has(spec.type)?<DataTable {...props}/>:spec.type==='kpi'?<Kpi {...props}/>:empty?<ChartMessage message="No records match the current filters."/>:error?<ChartMessage message={error}/>:spec.type==='semi_donut'?<SemiDonut {...props}/>:spec.type==='chord'?<Chord {...props}/>:figure&&'error'in figure?<ChartMessage message={figure.error}/>:figure&&<ChartBoundary reset={`${spec.type}-${spec.x}-${spec.y}`}><Suspense fallback={<ChartMessage message="Loading visualization…"/>}><Plot data={figure.data as any} layout={{...figure.layout,width:dimensions.width||undefined,height:dimensions.height||undefined} as any} config={{topojsonURL:'/topojson/',responsive:true,displaylogo:false,displayModeBar:'hover',scrollZoom:false,toImageButtonOptions:{format:'png',filename:String(spec.title??'chart'),scale:2},modeBarButtonsToRemove:['lasso2d','select2d','autoScale2d']} as any} style={{width:'100%',height:'100%'}} useResizeHandler onInitialized={(_figure:any,element:any)=>{graph.current=element;}} onUpdate={(_figure:any,element:any)=>{graph.current=element;}} onError={(failure:any)=>{console.error('Visualization rendering failed:',failure?.stack??failure);setError(`Unable to render ${chartName(spec.type)}. ${THREE_D_TYPES.has(spec.type)?'This chart needs WebGL support in your browser.':failure?.message??'Check the selected fields.'}`);}} onClick={(event:any)=>{const point=event.points?.[0];if(!point||!onSelect)return;if(spec.type==='map')onSelect(spec.x,point.lon,[{field:spec.y,value:point.lat}]);else if(spec.type==='pie3d')onSelect(spec.x,point.customdata?.[0]??point.data?.meta?.label);else if(['pie','donut','semi_donut','treemap','sunburst','funnel'].includes(spec.type))onSelect(spec.x,point.label??point.y);else if(spec.type==='horizontal_bar'||spec.type==='ranking')onSelect(spec.x,point.y);else if(!THREE_D_TYPES.has(spec.type)&&spec.x)onSelect(spec.x,point.x);}}/></Suspense></ChartBoundary>}
    {!TABLE_TYPES.has(spec.type)&&<div className="chart-actions" style={{position:'absolute',bottom:2,right:4,display:'flex',gap:2,opacity:.6,zIndex:3,background:'var(--surface,rgba(255,255,255,.85))',borderRadius:5}}><button type="button" aria-label="Export chart data CSV" title="Export chart data as CSV" onClick={()=>downloadCsv(spec,result)} style={iconButton}><Download size={12}/></button>{spec.type!=='kpi'&&!THREE_D_TYPES.has(spec.type)&&<button type="button" aria-label="Export chart SVG" title="Export SVG" onClick={exportSvg} style={{...iconButton,fontSize:9,fontWeight:600}}>SVG</button>}<button type="button" aria-label="Fullscreen chart" title="Fullscreen" onClick={fullscreen} style={iconButton}><Maximize2 size={12}/></button></div>}
  </div>;
}
