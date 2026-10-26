/** Run from frontend with `node tests/chart-renderer.mjs`. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scratch = await mkdtemp(path.join(tmpdir(), 'prism-renderer-'));
try {
  const bundle = path.join(scratch, 'chart.cjs');
  await build({ entryPoints: [path.join(root, 'src/components/Chart.tsx')], bundle: true, platform: 'node', format: 'cjs', external: ['react-plotly.js/factory', 'plotly.js-dist-min'], outfile: bundle, logLevel: 'silent' });
  const { buildFigure, formatValue, buildChordGeometry } = createRequire(import.meta.url)(bundle);
  const base = { id: 'chart', type: 'bar', title: 'Revenue', x: 'Region', y: 'Revenue' };
  const grouped = { labels: ['North', 'South'], series: [{ name: 'Revenue', values: [100, 200] }, { name: 'Cost', values: [60, 80] }], rows: [{ Region: 'North', Revenue: 100, Cost: 60 }, { Region: 'South', Revenue: 200, Cost: 80 }], columns: ['Region', 'Revenue', 'Cost'], row_count: 2 };
  let checked = 0;
  const figure = (type, result = grouped, extras = {}) => { const fig = buildFigure({ ...base, type, ...extras }, result); assert(fig.data.length, `${type}: rendered trace`); assert(fig.layout.autosize, `${type}: responsive dimensions`); checked++; return fig; };
  for (const type of ['bar', 'horizontal_bar', 'grouped_bar', 'stacked_bar', 'percent_bar', 'ranking', 'line', 'smooth_line', 'step_line', 'area', 'stacked_area', 'cumulative', 'moving_average', 'pie', 'donut', 'treemap', 'sunburst', 'pareto', 'waterfall', 'funnel', 'radar', 'timeline']) figure(type);
  assert.equal(figure('horizontal_bar').data[0].orientation, 'h');
  assert.equal(figure('stacked_bar').layout.barmode, 'relative');
  assert.deepEqual(figure('pie').data[0].values, [100, 200], 'pie uses actual aggregated values');
  assert.throws(() => figure('pie', { ...grouped, series: [{ name: 'Revenue', values: [-1, 200] }] }), /non-negative/);
  const pie3d = figure('pie3d');
  assert.equal(pie3d.data.length, 2, 'one real wedge mesh per positive category');
  for (const [index, wedge] of pie3d.data.entries()) {
    assert.equal(wedge.type, 'mesh3d');
    assert.equal(wedge.name, grouped.labels[index]);
    assert.equal(wedge.meta.value, grouped.series[0].values[index]);
    assert(Math.abs((wedge.meta.end_angle - wedge.meta.start_angle) / (2 * Math.PI) - grouped.series[0].values[index] / 300) < 1e-12, 'wedge angle equals exact data proportion');
    assert(Math.max(...wedge.z) > 0 && Math.min(...wedge.z) === 0, 'real three-dimensional extrusion');
    const edges = new Map();
    for (let face = 0; face < wedge.i.length; face++) {
      const vertices = [wedge.i[face], wedge.j[face], wedge.k[face]];
      assert(vertices.every((vertex) => vertex >= 0 && vertex < wedge.x.length), 'all faces reference existing vertices');
      const a = vertices.map((vertex) => [wedge.x[vertex], wedge.y[vertex], wedge.z[vertex]]);
      const u = a[1].map((value, axis) => value - a[0][axis]), v = a[2].map((value, axis) => value - a[0][axis]);
      const area = Math.hypot(u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]);
      assert(area > 0, 'mesh faces are nondegenerate');
      for (let side = 0; side < 3; side++) { const key = [vertices[side], vertices[(side + 1) % 3]].sort((a, b) => a - b).join(':'); edges.set(key, (edges.get(key) ?? 0) + 1); }
    }
    assert([...edges.values()].every((count) => count === 2), 'every closed wedge edge belongs to exactly two faces');
    assert.equal(wedge.customdata[0][0], grouped.labels[index]);
  }
  assert.throws(() => figure('pie3d', { ...grouped, series: [{ name: 'Revenue', values: [-1, 200] }] }), /non-negative/);
  assert.throws(() => figure('pie3d', { labels: ['Empty'], series: [{ name: 'Revenue', values: [0] }] }), /positive total/);
  assert.equal(figure('pie3d', { labels: ['Nothing', 'Positive'], series: [{ name: 'Revenue', values: [0, 10] }] }).data.length, 1, 'zero categories never fabricate visible wedges');
  const regression = figure('regression', { rows: [{ X: 1, Y: 3 }, { X: 2, Y: 5 }], regression: { x: [1, 2], y: [3, 5], slope: 2, intercept: 1, r_squared: 1, n: 2 } }, { x: 'X', y: 'Y' });
  assert.deepEqual(regression.data[0].y, [3, 5], 'regression retains actual observations');
  assert.deepEqual(regression.data[1].y, [3, 5], 'regression line uses backend fitted values');
  const density = figure('density', { density: { x: [0, 1, 2], y: [.2, .6, .2], bandwidth: .5 } });
  assert.deepEqual(density.data[0].y, [.2, .6, .2], 'density uses backend KDE estimates');
  assert.throws(() => figure('regression', { rows: [] }), /varying X/);
  assert.throws(() => figure('density', {}), /sufficient numerical/);
  for (const type of ['histogram', 'box', 'violin']) assert.equal(figure(type, { ...grouped, values: [100, 200] }).data[0].type, type);
  const raw = { rows: [{ X: 0, Y: 0, Z: 10 }, { X: 1, Y: 0, Z: 20 }, { X: 0, Y: 1, Z: 30 }, { X: 1, Y: 1, Z: 40 }], x_values: [0, 1], y_values: [0, 1], matrix: [[10, 20], [30, 40]], labels: [], series: [] };
  for (const type of ['scatter', 'bubble', 'scatter3d', 'surface3d', 'bar3d']) {
    const fig = figure(type, raw, { x: 'X', y: 'Y', z: 'Z' });
    if (type === 'bar3d') {
      assert.equal(fig.data[0].type, 'mesh3d');
      assert.equal(fig.data[0].x.length, 32, 'four real cuboids have eight vertices each');
      assert.equal(fig.data[0].i.length, 48, 'four cuboids have twelve mesh triangles each');
      assert.equal(Math.max(...fig.data[0].z), 40);
    }
    if (type === 'surface3d') assert.deepEqual(fig.data[0].z, [[10, 20], [30, 40]]);
    if (type === 'scatter3d') assert.deepEqual(fig.data[0].z, [10, 20, 30, 40]);
  }
  const tree = figure('treemap', { hierarchy: [{ name: 'North', children: [{ name: 'A', value: 10 }, { name: 'B', value: 20 }] }] });
  assert.deepEqual(tree.data[0].values, [30, 10, 20], 'hierarchical parent totals equal children');
  assert.equal(tree.data[0].parents[1], tree.data[0].ids[0]);
  for (const type of ['gauge', 'bullet', 'progress']) {
    assert.equal(figure(type, { value: 80 }, { target: 100 }).data[0].value, 80);
    assert.throws(() => figure(type, { value: 80 }), /positive target/);
    assert.throws(() => figure(type, { value: null }, { target: 100 }), /No numerical/);
  }
  const sankey = figure('sankey', { nodes: [{ id: 0, name: 'A' }, { id: 1, name: 'B' }], links: [{ source: 0, target: 1, value: 8 }] });
  assert.deepEqual(sankey.data[0].link.value, [8]);
  const calendar = figure('calendar', { labels: ['2026-01-01', '2026-01-02'], series: [{ name: 'Revenue', values: [10, 20] }] });
  assert.deepEqual(calendar.data[0].z.flat().filter((value) => value !== null).sort((a, b) => a - b), [10, 20]);
  assert.throws(() => figure('calendar', { labels: ['not a date'] }), /valid dates/);
  assert.deepEqual(figure('gantt', { rows: [{ task: 'Build', start: '2026-01-01', end: '2026-01-02', duration: 86400000 }] }).data[0].x, [86400000]);
  assert.equal(figure('heatmap', { columns: ['A', 'B'], matrix: [[1, .5], [.5, 1]] }).data[0].z[0][1], .5);
  const geography = figure('map', {rows:[{Longitude:77.209,Latitude:28.6139,Revenue:300,City:'Delhi'}]}, {x:'Longitude',y:'Latitude',z:'Revenue',series:'City'});
  assert.equal(geography.data[0].type,'scattergeo');
  assert.deepEqual(geography.data[0].lon,[77.209]);
  assert.deepEqual(geography.data[0].lat,[28.6139]);
  const interval = figure('confidence_band', {labels:['Jan','Feb'],bands:{lower:[8,16],center:[10,20],upper:[12,24]}}, {lower:'Lower',upper:'Upper'});
  assert.deepEqual(interval.data.map(trace=>trace.y),[[8,16],[12,24],[10,20]],'band uses actual provided bounds and center');
  assert.equal(interval.data[1].fill,'tonexty');
  assert.throws(()=>figure('confidence_band',{}),/actual center/);
  const chord=buildChordGeometry({nodes:[{id:0,name:'A'},{id:1,name:'B'},{id:2,name:'C'}],links:[{source:0,target:1,value:10},{source:0,target:2,value:30}]});
  assert.equal(chord.total,40);
  assert.equal(chord.ribbons.length,2);
  assert(Math.abs((chord.ribbons[1].sourceEnd-chord.ribbons[1].sourceStart)/(chord.ribbons[0].sourceEnd-chord.ribbons[0].sourceStart)-3)<1e-12,'ribbon arc width preserves exact 3:1 flow proportion');
  assert(chord.ribbons.every(ribbon=>!ribbon.path.includes('NaN')));
  assert.throws(()=>buildChordGeometry({nodes:[{id:0,name:'A'}],links:[{source:0,target:3,value:10}]}),/valid source/);
  assert.equal(formatValue(1234.56, { decimals: 1 }), '1,234.6');
  assert.equal(formatValue(12.5, { number_format: 'percent' }), '12.5%');
  assert.equal(formatValue(null), '—', 'missing KPIs never become zero');
  assert.throws(() => figure('unimplemented'), /not supported/);
  console.log(`Passed ${checked} chart figure checks plus geometry, numeric formatting and invalid configuration assertions.`);
} finally {
  await rm(scratch, { recursive: true, force: true });
}
