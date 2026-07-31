import type { Cluster, Item, CategoryTree, Stats } from './types';

let clustersCache: Cluster[] | null = null;
let itemsCache: Item[] | null = null;
let categoryTreeCache: CategoryTree | null = null;
let statsCache: Stats | null = null;

async function fetchJson<T>(path: string): Promise<T> {
    const res = await fetch(path);
    return res.json();
}

export async function getClusters(): Promise<Cluster[]> {
    if (clustersCache) return clustersCache;
    clustersCache = await fetchJson<Cluster[]>('/data/clusters.json');
    return clustersCache;
}

export async function getItems(): Promise<Item[]> {
    if (itemsCache) return itemsCache;
    itemsCache = await fetchJson<Item[]>('/data/items.json');
    return itemsCache;
}

export async function getCategoryTree(): Promise<CategoryTree> {
    if (categoryTreeCache) return categoryTreeCache;
    categoryTreeCache = await fetchJson<CategoryTree>('/data/category-tree.json');
    return categoryTreeCache;
}

export async function getStats(): Promise<Stats> {
    if (statsCache) return statsCache;
    statsCache = await fetchJson<Stats>('/data/stats.json');
    return statsCache;
}

export async function getClusterById(id: number): Promise<Cluster | undefined> {
    const clusters = await getClusters();
    return clusters.find(c => c.cluster_id === id);
}

export async function getItemsByClusterId(clusterId: number): Promise<Item[]> {
    const items = await getItems();
    return items.filter(i => i.cluster_id === clusterId);
}

export async function getClustersByCategory(topCategory: string, midCategory: string): Promise<Cluster[]> {
    const clusters = await getClusters();
    return clusters.filter(c => c.top_category === topCategory && c.mid_category === midCategory);
}
