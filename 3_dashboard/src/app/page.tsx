'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import { getClusters, getItems, getCategoryTree } from '@/lib/data';
import type { Cluster, Item, CategoryTree } from '@/lib/types';
import { HOSPITAL_COLORS, REVIEW_STATUS_LABELS, TOP_CATEGORIES } from '@/lib/types';
import { formatCurrency, formatNumber, getPriceGapPercent } from '@/lib/utils';
import { Building2, Hash, X, Search as SearchIcon, Download } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';

export default function ExplorerPage() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [categoryTree, setCategoryTree] = useState<CategoryTree | null>(null);
  const [loading, setLoading] = useState(true);

  const [activeTopCategory, setActiveTopCategory] = useState<string>(TOP_CATEGORIES[0]);
  const [activeMidCategory, setActiveMidCategory] = useState<string>('');

  const [hospitalFilter, setHospitalFilter] = useState<string>('all');
  const [matchFilter, setMatchFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('hospital_desc');
  const [searchQuery, setSearchQuery] = useState('');

  const [selectedCluster, setSelectedCluster] = useState<Cluster | null>(null);
  const [detailItems, setDetailItems] = useState<Item[]>([]);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getClusters(), getItems(), getCategoryTree()]).then(([c, i, t]) => {
      setClusters(c);
      setItems(i);
      setCategoryTree(t);
      setLoading(false);
      const firstTop = TOP_CATEGORIES[0];
      if (t[firstTop]) {
        const mids = Object.keys(t[firstTop]);
        if (mids.length > 0) setActiveMidCategory(mids[0]);
      }
    });
  }, []);

  const midCategories = useMemo(() => {
    if (!categoryTree || !categoryTree[activeTopCategory]) return [];
    return Object.entries(categoryTree[activeTopCategory])
      .sort((a, b) => b[1].cluster_count - a[1].cluster_count);
  }, [categoryTree, activeTopCategory]);

  const handleTopCategoryChange = useCallback((cat: string) => {
    setActiveTopCategory(cat);
    if (categoryTree && categoryTree[cat]) {
      const mids = Object.keys(categoryTree[cat]);
      setActiveMidCategory(mids.length > 0 ? mids[0] : '');
    }
    setSearchQuery('');
  }, [categoryTree]);

  const filteredClusters = useMemo(() => {
    let result = clusters.filter(
      c => c.top_category === activeTopCategory && c.mid_category === activeMidCategory
    );

    if (hospitalFilter === '2+') result = result.filter(c => c.hospital_count >= 2);
    else if (hospitalFilter === '3+') result = result.filter(c => c.hospital_count >= 3);
    else if (hospitalFilter === '5') result = result.filter(c => c.hospital_count === 5);

    if (matchFilter === '코드매칭') result = result.filter(c => c.match_method === '코드매칭');
    else if (matchFilter === 'AI클러스터링') result = result.filter(c => c.match_method === 'AI클러스터링');

    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(c =>
        c.representative_name.toLowerCase().includes(q) ||
        (c.code && c.code.toLowerCase().includes(q))
      );
    }

    switch (sortBy) {
      case 'hospital_desc': result.sort((a, b) => b.hospital_count - a.hospital_count); break;
      case 'price_gap': result.sort((a, b) => {
        const gapA = a.min_cost > 0 ? (a.max_cost - a.min_cost) / a.min_cost : 0;
        const gapB = b.min_cost > 0 ? (b.max_cost - b.min_cost) / b.min_cost : 0;
        return gapB - gapA;
      }); break;
      case 'item_desc': result.sort((a, b) => b.item_count - a.item_count); break;
    }

    return result;
  }, [clusters, activeTopCategory, activeMidCategory, hospitalFilter, matchFilter, sortBy, searchQuery]);

  const openDetail = useCallback((cluster: Cluster) => {
    setSelectedCluster(cluster);
    const clusterItems = items.filter(i => i.cluster_id === cluster.cluster_id);
    setDetailItems(clusterItems);
  }, [items]);

  const handleExportCsv = useCallback(() => {
    if (!selectedCluster || detailItems.length === 0) return;

    const headers = ['병원', '명칭', '코드', '비용', '구분', '특이사항'];
    const rows = detailItems.map(item => [
      item.hospital,
      `"${item.name.replace(/"/g, '""')}"`,
      item.code || '',
      item.cost,
      item.classification || '',
      `"${(item.note || '').replace(/"/g, '""')}"`
    ]);

    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');

    // Add BOM for Excel UTF-8 display
    const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `${selectedCluster.representative_name}_원본데이터.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [selectedCluster, detailItems]);

  if (loading) {
    return (
      <div>
        <div className="page-header"><h1>수가 비교 탐색기</h1><p>데이터 로딩 중...</p></div>
        <div className="explorer-layout">
          <div className="explorer-sidebar"><div className="skeleton" style={{ height: '100%', minHeight: 400 }} /></div>
          <div><div className="skeleton" style={{ height: 400 }} /></div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>수가 비교 탐색기</h1>
        <p>빅5 병원의 비급여 항목을 클러스터별로 비교합니다</p>
      </div>

      <div className="explorer-layout">
        <div className="explorer-sidebar">
          <div className="explorer-sidebar-header">
            <h2>카테고리</h2>
          </div>
          <div className="category-tabs">
            {TOP_CATEGORIES.map(cat => (
              <button
                key={cat}
                className={`category-tab ${activeTopCategory === cat ? 'active' : ''}`}
                onClick={() => handleTopCategoryChange(cat)}
              >
                {cat}
              </button>
            ))}
          </div>
          <div className="mid-category-list">
            {midCategories.map(([name, info]) => (
              <div
                key={name}
                className={`mid-category-item ${activeMidCategory === name ? 'active' : ''}`}
                onClick={() => setActiveMidCategory(name)}
              >
                <span className="name">{name}</span>
                <span className="mid-category-badge">{info.cluster_count}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="cluster-list-header">
            <div className="cluster-count">
              <strong>{activeMidCategory}</strong> — {filteredClusters.length}개 클러스터
            </div>
            <div className="filter-bar">
              <div style={{ position: 'relative' }}>
                <SearchIcon style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 16, height: 16, color: '#94a3b8' }} />
                <input
                  type="text"
                  placeholder="명칭/코드 검색..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  style={{ paddingLeft: 32, width: 180 }}
                />
              </div>
              <select value={hospitalFilter} onChange={(e) => setHospitalFilter(e.target.value)}>
                <option value="all">전체 병원</option>
                <option value="2+">2개+ 병원</option>
                <option value="3+">3개+ 병원</option>
                <option value="5">5개 전부</option>
              </select>
              <select value={matchFilter} onChange={(e) => setMatchFilter(e.target.value)}>
                <option value="all">전체 매칭</option>
                <option value="코드매칭">코드매칭</option>
                <option value="AI클러스터링">AI클러스터링</option>
              </select>
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="hospital_desc">병원수 많은순</option>
                <option value="price_gap">가격차이 큰순</option>
                <option value="item_desc">항목수 많은순</option>
              </select>
            </div>
          </div>

          {filteredClusters.length === 0 ? (
            <div className="empty-state">
              <SearchIcon />
              <p>조건에 맞는 클러스터가 없습니다</p>
            </div>
          ) : (
            <div className="cluster-grid">
              {filteredClusters.slice(0, 50).map(cluster => {
                const gap = getPriceGapPercent(cluster.min_cost, cluster.max_cost);
                return (
                  <div
                    key={cluster.cluster_id}
                    className="cluster-card"
                    onClick={() => openDetail(cluster)}
                  >
                    <div className="cluster-card-header">
                      <div className="cluster-card-title">{cluster.representative_name}</div>
                      <div className="cluster-card-badges">
                        <span className={`badge ${cluster.match_method === '코드매칭' ? 'badge-blue' : 'badge-purple'}`}>
                          {cluster.match_method}
                        </span>
                        {/* AI자동 상태 뱃지 표시 제거 (요청사항 #3) */}
                        {cluster.review_status !== 'ai_auto' && (
                          <span className={`badge ${cluster.review_status === 'human_confirmed' ? 'badge-green' : 'badge-orange'}`}>
                            {REVIEW_STATUS_LABELS[cluster.review_status]}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="cluster-card-stats">
                      <span><Building2 style={{ width: 14, height: 14 }} /> {cluster.hospital_count}개 병원</span>
                      <span><Hash style={{ width: 14, height: 14 }} /> {cluster.item_count}개 항목</span>
                      {cluster.code && <span style={{ fontSize: 12, color: '#94a3b8' }}>{cluster.code}</span>}
                    </div>
                    <div className="cluster-card-price">
                      <div className="price-range">
                        {formatCurrency(cluster.min_cost)} ~ {formatCurrency(cluster.max_cost)}
                      </div>
                      {gap > 0 && <div className="price-gap">차이 {gap}%</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {filteredClusters.length > 50 && (
            <p style={{ textAlign: 'center', color: '#94a3b8', marginTop: 20, fontSize: 13 }}>
              상위 50개만 표시 중 (총 {filteredClusters.length}개)
            </p>
          )}
        </div>
      </div>

      {selectedCluster && (
        <div className="detail-overlay" onClick={() => setSelectedCluster(null)}>
          <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
            <div className="detail-header">
              <div>
                <h2>{selectedCluster.representative_name}</h2>
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <span className={`badge ${selectedCluster.match_method === '코드매칭' ? 'badge-blue' : 'badge-purple'}`}>
                    {selectedCluster.match_method}
                  </span>
                  {selectedCluster.code && <span className="badge badge-gray">{selectedCluster.code}</span>}
                </div>
              </div>
              <button className="detail-close" onClick={() => setSelectedCluster(null)}>
                <X style={{ width: 18, height: 18 }} />
              </button>
            </div>

            <div style={{ display: 'flex', gap: 20, marginBottom: 24 }}>
              <div className="card" style={{ flex: 1, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>평균 비용</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{formatCurrency(selectedCluster.avg_cost)}</div>
              </div>
              <div className="card" style={{ flex: 1, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>가격차이율</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#dc2626' }}>
                  {getPriceGapPercent(selectedCluster.min_cost, selectedCluster.max_cost)}%
                </div>
              </div>
              <div className="card" style={{ flex: 1, textAlign: 'center' }}>
                <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>병원 수</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: '#3b82f6' }}>{selectedCluster.hospital_count}개</div>
              </div>
            </div>

            {detailItems.length > 0 && (() => {
              const hospitalPrices = selectedCluster.hospital_list.map(h => {
                const hItems = detailItems.filter(i => i.hospital === h);
                const avgCost = hItems.length > 0
                  ? hItems.reduce((sum, i) => sum + i.cost, 0) / hItems.length
                  : 0;
                return { name: h, cost: Math.round(avgCost) };
              }).filter(h => h.cost > 0).sort((a, b) => b.cost - a.cost);

              return (
                <div className="card" style={{ marginBottom: 24 }}>
                  <div className="card-title">병원별 가격 비교</div>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={hospitalPrices} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={(v) => formatCurrency(v)} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 13, fill: '#334155' }} width={65} />
                      <Tooltip formatter={(value) => Number(value).toLocaleString() + '원'} />
                      <Bar dataKey="cost" radius={[0, 6, 6, 0]} barSize={24}>
                        {hospitalPrices.map((entry) => (
                          <Cell key={entry.name} fill={HOSPITAL_COLORS[entry.name] || '#94a3b8'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              );
            })()}

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <div className="card-title" style={{ marginBottom: 0 }}>상세 항목 목록</div>
                {/* 엑셀 다운로드 버튼 (요청사항 #2) */}
                <button className="btn btn-outline" onClick={handleExportCsv} style={{ padding: '6px 12px', fontSize: 12 }}>
                  <Download style={{ width: 14, height: 14 }} /> 원본 데이터 다운로드
                </button>
              </div>
              <div className="data-table-wrapper">
                <table className="price-table">
                  <thead>
                    <tr>
                      <th>병원</th>
                      <th>명칭</th>
                      <th>코드</th>
                      <th>비용</th>
                      <th>구분</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailItems
                      .sort((a, b) => b.cost - a.cost)
                      .map((item, idx) => {
                        const maxCost = Math.max(...detailItems.map(i => i.cost));
                        const minCost = Math.min(...detailItems.filter(i => i.cost > 0).map(i => i.cost));
                        const isHigh = item.cost === maxCost && detailItems.length > 1;
                        const isLow = item.cost === minCost && detailItems.length > 1 && item.cost > 0;
                        return (
                          <tr key={idx}>
                            <td>
                              <span className="hospital-dot" style={{ background: HOSPITAL_COLORS[item.hospital] || '#94a3b8' }} />
                              {item.hospital}
                            </td>
                            <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {item.name}
                            </td>
                            <td style={{ fontSize: 12, color: '#94a3b8' }}>{item.code || '-'}</td>
                            <td className={isHigh ? 'price-high' : isLow ? 'price-low' : ''}>
                              {item.cost > 0 ? item.cost.toLocaleString() + '원' : '-'}
                            </td>
                            <td style={{ fontSize: 12 }}>{item.classification || '-'}</td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
              <button
                className="btn btn-success"
                style={{ flex: 1 }}
                onClick={() => {
                  setToastMessage('클러스터 정상 확인이 완료되었습니다.');
                  setTimeout(() => setToastMessage(null), 3000);
                  setSelectedCluster(null);
                }}
              >
                ✓ 클러스터 확인 완료
              </button>
              <button
                className="btn btn-danger"
                style={{ flex: 1 }}
                onClick={() => {
                  setToastMessage('오류 신고가 접수되었습니다. (피드백 결과 반영 예정)');
                  setTimeout(() => setToastMessage(null), 3000);
                  setSelectedCluster(null);
                }}
              >
                ✗ 오류 신고
              </button>
            </div>
          </div>
        </div>
      )}

      {toastMessage && (
        <div style={{
          position: 'fixed', bottom: 40, left: '50%', transform: 'translateX(-50%)',
          background: '#1e293b', color: '#fff', padding: '12px 24px', borderRadius: 8,
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)', zIndex: 9999, fontWeight: 600, fontSize: 14,
          animation: 'fadeInOut 3s ease'
        }}>
          {toastMessage}
        </div>
      )}
    </div>
  );
}
