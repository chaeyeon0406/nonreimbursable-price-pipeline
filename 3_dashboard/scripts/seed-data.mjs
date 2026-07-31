/**
 * CSV → JSON 데이터 변환 스크립트
 * v4_cluster_summary.csv → public/data/clusters.json
 * v4_cluster_result.csv  → public/data/items.json
 */
import fs from 'fs';
import path from 'path';
import { parse } from 'csv-parse/sync';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const DATA_DIR = path.resolve(ROOT, '..'); // parent dir with CSV files
const OUT_DIR = path.resolve(ROOT, 'public', 'data');

fs.mkdirSync(OUT_DIR, { recursive: true });

// ─── Clusters ──────────────────────────────────────────
console.log('Processing clusters...');
const clustersCsv = fs.readFileSync(path.join(DATA_DIR, 'v4_cluster_summary.csv'), 'utf-8');
const clustersRaw = parse(clustersCsv, { columns: true, skip_empty_lines: true, bom: true });

const clusters = clustersRaw.map((r) => ({
    cluster_id: parseInt(r.cluster_id, 10),
    top_category: r['최상위계층'],
    mid_category: r['표준_중분류명'],
    match_method: r['매칭방법'],
    representative_name: r['대표명칭'],
    item_count: parseInt(r['항목수'], 10) || 0,
    hospital_count: parseInt(r['병원수'], 10) || 0,
    hospital_list: r['병원목록'] ? r['병원목록'].split(',').map((s) => s.trim()) : [],
    code: r['코드'] || null,
    avg_cost: parseFloat(r['평균비용']) || 0,
    min_cost: parseFloat(r['최저비용']) || 0,
    max_cost: parseFloat(r['최고비용']) || 0,
    review_status: 'ai_auto',
}));

fs.writeFileSync(path.join(OUT_DIR, 'clusters.json'), JSON.stringify(clusters, null, 0));
console.log(`  → ${clusters.length} clusters saved`);

// ─── Items ─────────────────────────────────────────────
console.log('Processing items...');
const itemsCsv = fs.readFileSync(path.join(DATA_DIR, 'v4_cluster_result.csv'), 'utf-8');
const itemsRaw = parse(itemsCsv, { columns: true, skip_empty_lines: true, bom: true });

const items = itemsRaw.map((r, i) => ({
    id: i + 1,
    hospital: r['병원'],
    top_category: r['최상위계층'],
    mid_category: r['표준_중분류명'],
    sub_category: r['표준_소분류명'] || null,
    name: r['명칭'],
    code: r['코드'] || null,
    classification: r['구분'] || null,
    cost: parseFloat(r['비용']) || 0,
    note: r['특이사항'] || null,
    cluster_id: parseInt(r.cluster_id, 10),
    match_method: r.match_method,
}));

fs.writeFileSync(path.join(OUT_DIR, 'items.json'), JSON.stringify(items, null, 0));
console.log(`  → ${items.length} items saved`);

// ─── Category tree stats (pre-computed) ────────────────
console.log('Building category tree...');
const categoryTree = {};
for (const c of clusters) {
    if (!categoryTree[c.top_category]) categoryTree[c.top_category] = {};
    if (!categoryTree[c.top_category][c.mid_category]) {
        categoryTree[c.top_category][c.mid_category] = { cluster_count: 0, item_count: 0 };
    }
    categoryTree[c.top_category][c.mid_category].cluster_count++;
    categoryTree[c.top_category][c.mid_category].item_count += c.item_count;
}
fs.writeFileSync(path.join(OUT_DIR, 'category-tree.json'), JSON.stringify(categoryTree, null, 2));
console.log('  → category-tree.json saved');

// ─── Stats ─────────────────────────────────────────────
const stats = {
    total_items: items.length,
    total_clusters: clusters.length,
    multi_hospital_clusters: clusters.filter((c) => c.hospital_count >= 2).length,
    pending_review: clusters.filter((c) => c.match_method === 'AI클러스터링' && c.review_status === 'ai_auto').length,
    by_top_category: {},
    by_match_method: { '코드매칭': 0, 'AI클러스터링': 0 },
    by_hospital: {},
};
for (const item of items) {
    stats.by_top_category[item.top_category] = (stats.by_top_category[item.top_category] || 0) + 1;
    if (stats.by_match_method[item.match_method] !== undefined) {
        stats.by_match_method[item.match_method]++;
    }
    stats.by_hospital[item.hospital] = (stats.by_hospital[item.hospital] || 0) + 1;
}
fs.writeFileSync(path.join(OUT_DIR, 'stats.json'), JSON.stringify(stats, null, 2));
console.log('  → stats.json saved');

console.log('\n✅ Data seeding complete!');
