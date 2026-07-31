'use client';

import { useEffect, useState, useMemo } from 'react';
import { getClusters, getItems, getStats } from '@/lib/data';
import type { Cluster, Item, Stats } from '@/lib/types';
import { HOSPITAL_COLORS, TOP_CATEGORIES, MATCH_METHOD_COLORS, REVIEW_STATUS_LABELS, REVIEW_STATUS_COLORS } from '@/lib/types';
import { formatCurrency, formatNumber, getPriceGapPercent } from '@/lib/utils';
import { Download, TrendingUp, AlertTriangle, BarChart3, Lock, Database, Layers, GitCompareArrows, ClipboardCheck } from 'lucide-react';
import {
    BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid, Legend,
    PieChart, Pie
} from 'recharts';

export default function ReportsPage() {
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [passwordInput, setPasswordInput] = useState('');

    const [clusters, setClusters] = useState<Cluster[]>([]);
    const [items, setItems] = useState<Item[]>([]);
    const [stats, setStats] = useState<Stats | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (isAuthenticated) {
            Promise.all([getClusters(), getItems(), getStats()]).then(([c, i, s]) => {
                setClusters(c);
                setItems(i);
                setStats(s);
                setLoading(false);
            });
        }
    }, [isAuthenticated]);

    const handleLogin = (e: React.FormEvent) => {
        e.preventDefault();
        if (passwordInput === 'admin1234') {
            setIsAuthenticated(true);
        } else {
            alert('비밀번호가 틀렸습니다.');
        }
    };

    const topPriceGapClusters = useMemo(() => {
        if (!clusters.length) return [];
        return clusters
            .filter(c => c.hospital_count >= 2 && c.min_cost > 0)
            .map(c => ({
                ...c,
                gap_percent: getPriceGapPercent(c.min_cost, c.max_cost),
                price_diff: c.max_cost - c.min_cost,
            }))
            .sort((a, b) => b.gap_percent - a.gap_percent)
            .slice(0, 15);
    }, [clusters]);

    const hospitalAvgByCategory = useMemo(() => {
        if (!items.length) return [];
        const hospitals = ['서울대', '삼성', '세브란스', '아산', '서울성모'];
        const categories = [...new Set(items.map(i => i.top_category))];
        return categories.map(cat => {
            const row: Record<string, string | number> = { category: cat };
            hospitals.forEach(h => {
                const hItems = items.filter(i => i.top_category === cat && i.hospital === h && i.cost > 0);
                row[h] = hItems.length > 0 ? Math.round(hItems.reduce((s, i) => s + i.cost, 0) / hItems.length) : 0;
            });
            return row;
        });
    }, [items]);

    const modelPerformance = useMemo(() => {
        if (!clusters.length) return null;
        const aiClusters = clusters.filter(c => c.match_method === 'AI클러스터링');
        const codeClusters = clusters.filter(c => c.match_method === '코드매칭');
        return {
            ai_total: aiClusters.length,
            code_total: codeClusters.length,
            ai_confirmed: aiClusters.filter(c => c.review_status === 'human_confirmed').length,
            ai_corrected: aiClusters.filter(c => c.review_status === 'human_corrected').length,
            ai_pending: aiClusters.filter(c => c.review_status === 'ai_auto').length,
        };
    }, [clusters]);

    if (!isAuthenticated) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
                <div className="card" style={{ width: 400, textAlign: 'center', padding: 40 }}>
                    <div style={{ display: 'inline-flex', padding: 16, background: '#f8fafc', borderRadius: '50%', marginBottom: 20 }}>
                        <Lock style={{ width: 32, height: 32, color: '#3b82f6' }} />
                    </div>
                    <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>관리자 전용 페이지</h2>
                    <p style={{ color: '#64748b', fontSize: 14, marginBottom: 24 }}>분석 리포트는 관리자만 접근할 수 있습니다.</p>
                    <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <input
                            type="password"
                            placeholder="비밀번호 (admin1234)"
                            value={passwordInput}
                            onChange={e => setPasswordInput(e.target.value)}
                            style={{ width: '100%', padding: '12px 16px', borderRadius: 8, border: '1px solid #e2e8f0', outline: 'none' }}
                            autoFocus
                        />
                        <button type="submit" className="btn btn-primary" style={{ padding: 12, width: '100%', justifyContent: 'center' }}>
                            인증하기
                        </button>
                    </form>
                </div>
            </div>
        );
    }

    if (loading || !stats || !modelPerformance) {
        return (
            <div>
                <div className="page-header"><h1>종합 분석 리포트</h1></div>
                <div className="skeleton" style={{ height: 400 }} />
            </div>
        );
    }

    const statCards = [
        { label: '전체 항목 수', value: formatNumber(stats.total_items), icon: Database, color: '#3b82f6', bg: '#eff6ff' },
        { label: '전체 클러스터 수', value: formatNumber(stats.total_clusters), icon: Layers, color: '#8b5cf6', bg: '#f5f3ff' },
        { label: '2개+병원 비교 가능', value: formatNumber(stats.multi_hospital_clusters), icon: GitCompareArrows, color: '#10b981', bg: '#f0fdf4' },
        { label: '검토 대기 건수', value: formatNumber(stats.pending_review), icon: ClipboardCheck, color: '#f59e0b', bg: '#fffbeb' },
    ];

    const pieData = Object.entries(stats.by_top_category).map(([name, value]) => ({ name, value }));
    const TOP_CATEGORY_COLORS: Record<string, string> = {
        '행위': '#3b82f6', '치료재료': '#8b5cf6', '약제': '#10b981', '제증명수수료': '#f59e0b',
    };

    const codeMatchCount = stats.by_match_method['코드매칭'] || 0;
    const aiCount = stats.by_match_method['AI클러스터링'] || 0;
    const total = codeMatchCount + aiCount;
    const codePercent = total ? Math.round((codeMatchCount / total) * 100) : 0;
    const aiPercent = 100 - codePercent;

    return (
        <div>
            <div className="page-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1>종합 분석 리포트</h1>
                        <p>전체 현황, 수가 분석 및 AI 모델 성능 추적 (관리자 전용)</p>
                    </div>
                    <button className="btn btn-outline">
                        <Download style={{ width: 16, height: 16 }} /> 리포트 PDF 다운로드
                    </button>
                </div>
            </div>

            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, borderBottom: '2px solid #e2e8f0', paddingBottom: 8 }}>1. 데이터베이스 현황 요약</h2>

            {/* Stat Cards */}
            <div className="stat-cards">
                {statCards.map((s) => {
                    const Icon = s.icon;
                    return (
                        <div className="stat-card" key={s.label}>
                            <div className="stat-icon" style={{ background: s.bg }}>
                                <Icon style={{ width: 22, height: 22, color: s.color }} />
                            </div>
                            <div className="stat-value">{s.value}</div>
                            <div className="stat-label">{s.label}</div>
                        </div>
                    );
                })}
            </div>

            <div className="charts-grid">
                {/* Donut Chart - Category Distribution */}
                <div className="card">
                    <div className="card-title">최상위계층별 항목 분포</div>
                    <ResponsiveContainer width="100%" height={280}>
                        <PieChart>
                            <Pie
                                data={pieData}
                                cx="50%"
                                cy="50%"
                                innerRadius={70}
                                outerRadius={110}
                                paddingAngle={3}
                                dataKey="value"
                                label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(1)}%`}
                            >
                                {pieData.map((entry) => (
                                    <Cell key={entry.name} fill={TOP_CATEGORY_COLORS[entry.name] || '#94a3b8'} />
                                ))}
                            </Pie>
                            <Tooltip formatter={(value) => formatNumber(Number(value)) + '건'} />
                        </PieChart>
                    </ResponsiveContainer>
                </div>

                {/* 매칭방법별 비율 */}
                <div className="card">
                    <div className="card-title">매칭방법 & 리뷰 상태</div>
                    <div style={{ marginBottom: 24 }}>
                        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>매칭방법별 비율</div>
                        <div className="status-bar">
                            <div className="status-bar-segment" style={{ width: `${codePercent}%`, background: MATCH_METHOD_COLORS['코드매칭'] }}>
                                코드매칭 {codePercent}%
                            </div>
                            <div className="status-bar-segment" style={{ width: `${aiPercent}%`, background: MATCH_METHOD_COLORS['AI클러스터링'] }}>
                                AI {aiPercent}%
                            </div>
                        </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>클러스터 맵핑 검수 상태</div>
                        {Object.entries(REVIEW_STATUS_LABELS).map(([key, label]) => {
                            const count = key === 'ai_auto' ? stats.pending_review : 0;
                            return (
                                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                    <div style={{ width: 10, height: 10, borderRadius: '50%', background: REVIEW_STATUS_COLORS[key] }} />
                                    <span style={{ flex: 1, fontSize: 13, fontWeight: 500 }}>{label}</span>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: REVIEW_STATUS_COLORS[key] }}>
                                        {key === 'ai_auto' ? formatNumber(count) : '0'}건
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>

            <h2 style={{ fontSize: 18, fontWeight: 700, marginTop: 40, marginBottom: 16, borderBottom: '2px solid #e2e8f0', paddingBottom: 8 }}>2. 수가 편차 분석</h2>

            <div className="charts-grid">
                {/* Top Price Gap Clusters */}
                <div className="card">
                    <div className="card-title">가격 편차 TOP 15 클러스터</div>
                    <ResponsiveContainer width="100%" height={400}>
                        <BarChart data={topPriceGapClusters} layout="vertical" margin={{ left: 20, right: 20 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                            <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={(v) => v + '%'} />
                            <YAxis
                                type="category"
                                dataKey="representative_name"
                                tick={{ fontSize: 11, fill: '#334155' }}
                                width={130}
                                tickFormatter={(v: string) => v.length > 18 ? v.slice(0, 18) + '...' : v}
                            />
                            <Tooltip
                                formatter={(value) => value + '%'}
                                labelFormatter={(name) => `클러스터: ${name}`}
                            />
                            <Bar dataKey="gap_percent" fill="#dc2626" radius={[0, 6, 6, 0]} barSize={18} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>

                {/* Hospital Average Cost by Category */}
                <div className="card">
                    <div className="card-title">최상위계층별 병원 평균수가</div>
                    <ResponsiveContainer width="100%" height={400}>
                        <BarChart data={hospitalAvgByCategory} margin={{ top: 20 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                            <XAxis dataKey="category" tick={{ fontSize: 12, fill: '#334155' }} />
                            <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={(v) => formatCurrency(v)} />
                            <Tooltip formatter={(value) => Number(value).toLocaleString() + '원'} />
                            <Legend />
                            {['서울대', '삼성', '세브란스', '아산', '서울성모'].map(h => (
                                <Bar key={h} dataKey={h} fill={HOSPITAL_COLORS[h]} radius={[4, 4, 0, 0]} barSize={16} />
                            ))}
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            <h2 style={{ fontSize: 18, fontWeight: 700, marginTop: 40, marginBottom: 16, borderBottom: '2px solid #e2e8f0', paddingBottom: 8 }}>3. AI 클러스터링 모니터링 실적</h2>

            {/* Model Performance Summary */}
            <div className="stat-cards" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
                <div className="stat-card">
                    <div className="stat-icon" style={{ background: '#f5f3ff' }}>
                        <BarChart3 style={{ width: 22, height: 22, color: '#8b5cf6' }} />
                    </div>
                    <div className="stat-value">{formatNumber(modelPerformance.ai_total)}</div>
                    <div className="stat-label">AI 클러스터링 건수</div>
                </div>
                <div className="stat-card">
                    <div className="stat-icon" style={{ background: '#f8fafc' }}>
                        <ClipboardCheck style={{ width: 22, height: 22, color: '#334155' }} />
                    </div>
                    <div className="stat-value">{modelPerformance.ai_confirmed}</div>
                    <div className="stat-label">사람 확인 완료 건수</div>
                </div>
                <div className="stat-card">
                    <div className="stat-icon" style={{ background: '#fff7ed' }}>
                        <AlertTriangle style={{ width: 22, height: 22, color: '#f59e0b' }} />
                    </div>
                    <div className="stat-value">{modelPerformance.ai_corrected}</div>
                    <div className="stat-label">사람 수정 건수 (오류)</div>
                </div>
                <div className="stat-card">
                    <div className="stat-icon" style={{ background: '#fef2f2' }}>
                        <AlertTriangle style={{ width: 22, height: 22, color: '#dc2626' }} />
                    </div>
                    <div className="stat-value">
                        {modelPerformance.ai_confirmed + modelPerformance.ai_corrected > 0
                            ? ((modelPerformance.ai_corrected / (modelPerformance.ai_confirmed + modelPerformance.ai_corrected)) * 100).toFixed(1) + '%'
                            : '0%'}
                    </div>
                    <div className="stat-label">오류/수정 비율</div>
                </div>
            </div>

            {/* Price Gap Table */}
            <div className="card" style={{ marginTop: 20 }}>
                <div className="card-title">가격 편차 상세 데이터 (전체)</div>
                <div className="data-table-wrapper">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>순위</th>
                                <th>클러스터명</th>
                                <th>중분류</th>
                                <th>최저가</th>
                                <th>최고가</th>
                                <th>가격차이</th>
                                <th>편차율</th>
                                <th>병원수</th>
                            </tr>
                        </thead>
                        <tbody>
                            {topPriceGapClusters.slice(0, 20).map((c, idx) => (
                                <tr key={c.cluster_id}>
                                    <td style={{ fontWeight: 700, color: idx < 3 ? '#dc2626' : '#64748b' }}>{idx + 1}</td>
                                    <td style={{ fontWeight: 500 }}>{c.representative_name}</td>
                                    <td style={{ fontSize: 12, color: '#64748b' }}>{c.mid_category}</td>
                                    <td>{formatCurrency(c.min_cost)}</td>
                                    <td>{formatCurrency(c.max_cost)}</td>
                                    <td style={{ fontWeight: 600 }}>{formatCurrency(c.price_diff)}</td>
                                    <td>
                                        <span className={`badge ${c.gap_percent > 200 ? 'badge-red' : c.gap_percent > 100 ? 'badge-orange' : 'badge-gray'}`}>
                                            {c.gap_percent}%
                                        </span>
                                    </td>
                                    <td>{c.hospital_count}개</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
