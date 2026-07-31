'use client';

import { useState, useEffect, useMemo } from 'react';
import { getClusters, getItems } from '@/lib/data';
import type { Cluster, Item, FeedbackLog } from '@/lib/types';
import { formatCurrency } from '@/lib/utils';
import { Search as SearchIcon, X, Check, ArrowRight, AlertTriangle, Plus, Clock, Target, Hash, Building2 } from 'lucide-react';

// 초기 Mock 데이터
const MOCK_INITIAL_LOGS: FeedbackLog[] = [
    { id: 1, item_id: 0, item_name: 'PET CT(F-18)', from_cluster_id: 8123, from_cluster_name: 'F-18 플루트메타몰', to_cluster_id: 8124, to_cluster_name: 'F-18 플로르베타벤', action: 'reassign', reason: '약제 성분 오분류', created_by: 'admin', created_at: '2023-11-20 14:30' },
    { id: 2, item_id: 0, item_name: '로봇수술료', from_cluster_id: 9012, from_cluster_name: '다빈치 로봇수술', to_cluster_id: 9012, to_cluster_name: '-', action: 'confirm', reason: '정상 분류 확인 (확정)', created_by: 'reviewer_1', created_at: '2023-11-20 11:15' },
];

export default function FeedbackPage() {
    const [clusters, setClusters] = useState<Cluster[]>([]);
    const [items, setItems] = useState<Item[]>([]);
    const [logs, setLogs] = useState<FeedbackLog[]>(MOCK_INITIAL_LOGS);
    const [loading, setLoading] = useState(true);

    // 현재 수정한 클러스터 상태를 프론트에서 임시 보관 (DB 역할)
    const [localClusterStatus, setLocalClusterStatus] = useState<Record<number, 'human_confirmed' | 'human_corrected'>>({});

    const [tab, setTab] = useState<'queue' | 'history'>('queue');

    // 오류 신고 패널 상태
    const [errorPanelCluster, setErrorPanelCluster] = useState<Cluster | null>(null);
    const [searchTargetQuery, setSearchTargetQuery] = useState('');
    const [selectedTargetClusterId, setSelectedTargetClusterId] = useState<number | 'new' | null>(null);
    const [reasonInput, setReasonInput] = useState('');

    useEffect(() => {
        Promise.all([getClusters(), getItems()]).then(([c, i]) => {
            // Mock Confidence Score 부여
            const clustersWithScore = c.map(cl => ({
                ...cl,
                // 60% ~ 99% 사이의 점수를 id 기반으로 생성
                confidence_score: 60 + (cl.cluster_id % 40)
            }));
            setClusters(clustersWithScore);
            setItems(i);
            setLoading(false);
        });
    }, []);

    // 1. Review Queue 데이터: AI클러스터링 & 리뷰 안 된 것 (낮은 신뢰도 순)
    const reviewQueue = useMemo(() => {
        return clusters
            .filter(c => c.match_method === 'AI클러스터링' && c.review_status === 'ai_auto' && !localClusterStatus[c.cluster_id])
            .sort((a, b) => (a as any).confidence_score - (b as any).confidence_score);
    }, [clusters, localClusterStatus]);

    // AI 추천 후보 클러스터 (선택한 클러스터와 같은 중분류에 속하는 다른 클러스터 3개)
    const candidateClusters = useMemo(() => {
        if (!errorPanelCluster) return [];
        return clusters
            .filter(c => c.mid_category === errorPanelCluster.mid_category && c.cluster_id !== errorPanelCluster.cluster_id)
            .slice(0, 3);
    }, [errorPanelCluster, clusters]);

    // 후보 검색 결과
    const searchedClusters = useMemo(() => {
        if (!searchTargetQuery.trim()) return [];
        return clusters
            .filter(c => c.cluster_id !== errorPanelCluster?.cluster_id &&
                (c.representative_name.includes(searchTargetQuery) || c.code?.includes(searchTargetQuery)))
            .slice(0, 5);
    }, [searchTargetQuery, clusters, errorPanelCluster]);

    // Handler: 정상 확인 (✓)
    const handleConfirm = (cluster: Cluster) => {
        setLocalClusterStatus(prev => ({ ...prev, [cluster.cluster_id]: 'human_confirmed' }));
        setLogs(prev => [{
            id: Date.now(),
            item_id: 0,
            item_name: '전체 항목',
            from_cluster_id: cluster.cluster_id,
            from_cluster_name: cluster.representative_name,
            to_cluster_id: cluster.cluster_id,
            to_cluster_name: '-',
            action: 'confirm',
            reason: 'AI 맵핑 정상 확인',
            created_by: '관리자',
            created_at: new Date().toISOString().replace('T', ' ').slice(0, 16)
        }, ...prev]);
    };

    // Handler: 오류 신고 제출
    const handleSubmitError = () => {
        if (!errorPanelCluster) return;
        if (!selectedTargetClusterId) {
            alert('이동할 클러스터를 선택해주세요.');
            return;
        }

        const targetName = selectedTargetClusterId === 'new'
            ? '(신규 클러스터 생성)'
            : clusters.find(c => c.cluster_id === selectedTargetClusterId)?.representative_name || '알 수 없음';

        setLocalClusterStatus(prev => ({ ...prev, [errorPanelCluster.cluster_id]: 'human_corrected' }));
        setLogs(prev => [{
            id: Date.now(),
            item_id: 0,
            item_name: '전체 오류 이동',
            from_cluster_id: errorPanelCluster.cluster_id,
            from_cluster_name: errorPanelCluster.representative_name,
            to_cluster_id: selectedTargetClusterId === 'new' ? 0 : selectedTargetClusterId,
            to_cluster_name: targetName,
            action: selectedTargetClusterId === 'new' ? 'new_cluster' : 'reassign',
            reason: reasonInput || '오분류 수정',
            created_by: '관리자',
            created_at: new Date().toISOString().replace('T', ' ').slice(0, 16)
        }, ...prev]);

        // 패널 닫기 및 초기화
        setErrorPanelCluster(null);
        setSearchTargetQuery('');
        setSelectedTargetClusterId(null);
        setReasonInput('');
    };

    if (loading) {
        return (
            <div>
                <div className="page-header"><h1>피드백 & 오류 수정</h1><p>로딩 중...</p></div>
                <div className="skeleton" style={{ height: 400 }} />
            </div>
        );
    }

    return (
        <div>
            <div className="page-header">
                <h1>피드백 & 오류 수정</h1>
                <p>AI가 자동 분류한 클러스터를 검토하고, 오류를 교정하여 모델 학습에 반영합니다.</p>
            </div>

            <div style={{ display: 'flex', gap: 12, marginBottom: 24, borderBottom: '1px solid #e2e8f0', paddingBottom: 16 }}>
                <button className={`btn ${tab === 'queue' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setTab('queue')}>
                    검토 대기 큐 <span className="badge badge-blue" style={{ marginLeft: 6 }}>{reviewQueue.length}건</span>
                </button>
                <button className={`btn ${tab === 'history' ? 'btn-primary' : 'btn-outline'}`} onClick={() => setTab('history')}>
                    피드백 처리 로그
                </button>
            </div>

            {/* Review Queue Tab */}
            {tab === 'queue' && (
                <div className="review-queue">
                    <div style={{ padding: '0 8px', marginBottom: 8, fontSize: 13, color: '#64748b', display: 'flex', justifyContent: 'space-between' }}>
                        <span>낮은 Confidence Score 순으로 정렬되어 있습니다.</span>
                        <span>전체 대기 건수: {reviewQueue.length}건</span>
                    </div>

                    {reviewQueue.slice(0, 50).map(cluster => {
                        const score = (cluster as any).confidence_score;
                        return (
                            <div key={cluster.cluster_id} className="review-item" style={{ borderLeft: score < 75 ? '4px solid #f59e0b' : '4px solid #3b82f6' }}>
                                <div style={{ width: 80, textAlign: 'center' }}>
                                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Confidence</div>
                                    <div style={{ fontSize: 20, fontWeight: 800, color: score < 75 ? '#d97706' : '#2563eb' }}>{score}%</div>
                                </div>

                                <div className="review-item-info">
                                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{cluster.top_category} {'>'} {cluster.mid_category}</div>
                                    <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>{cluster.representative_name}</div>
                                    <div style={{ display: 'flex', gap: 16, fontSize: 13, color: '#475569' }}>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Building2 style={{ width: 14, height: 14 }} /> {cluster.hospital_count}개 병원</span>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Hash style={{ width: 14, height: 14 }} /> {cluster.item_count}개 항목</span>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Target style={{ width: 14, height: 14 }} /> 가격범위: {formatCurrency(cluster.min_cost)} ~ {formatCurrency(cluster.max_cost)}</span>
                                    </div>
                                </div>

                                <div className="review-item-actions" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <button className="btn btn-success" onClick={() => handleConfirm(cluster)} style={{ width: 120, justifyContent: 'center' }}>
                                        <Check style={{ width: 16, height: 16 }} /> 정상 확인
                                    </button>
                                    <button className="btn btn-danger" onClick={() => setErrorPanelCluster(cluster)} style={{ width: 120, justifyContent: 'center' }}>
                                        <AlertTriangle style={{ width: 16, height: 16 }} /> 오류 신고
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                    {reviewQueue.length > 50 && (
                        <div style={{ textAlign: 'center', padding: 20, color: '#64748b', fontSize: 13 }}>상위 50건만 표시 중입니다.</div>
                    )}
                </div>
            )}

            {/* History Tab */}
            {tab === 'history' && (
                <div className="card">
                    <div className="card-title">피드백 통계 및 로그</div>
                    <p style={{ fontSize: 13, color: '#64748b', marginBottom: 20 }}>이곳에서 수정된 내역은 모델 파인튜닝 시 학습 데이터로 활용됩니다.</p>
                    <div className="data-table-wrapper">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>시간</th>
                                    <th>작업자</th>
                                    <th>대상 항목/클러스터</th>
                                    <th>변경 내용</th>
                                    <th>사유</th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.map(log => (
                                    <tr key={log.id}>
                                        <td style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>
                                            <Clock style={{ width: 12, height: 12, display: 'inline', marginRight: 4, verticalAlign: -2 }} />
                                            {log.created_at}
                                        </td>
                                        <td>{log.created_by}</td>
                                        <td style={{ fontWeight: 500 }}>{log.from_cluster_name}</td>
                                        <td>
                                            {log.action !== 'confirm' ? (
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                                    <span style={{ textDecoration: 'line-through', color: '#94a3b8', fontSize: 12 }}>{log.from_cluster_name}</span>
                                                    <ArrowRight style={{ width: 14, height: 14, color: '#3b82f6' }} />
                                                    <span style={{ color: '#2563eb', fontWeight: 600 }}>{log.to_cluster_name}</span>
                                                </div>
                                            ) : (
                                                <span className="badge badge-green">분류 정상 확정</span>
                                            )}
                                        </td>
                                        <td style={{ fontSize: 13 }}>{log.reason}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Error Report Side Panel */}
            {errorPanelCluster && (
                <div className="detail-overlay" onClick={() => setErrorPanelCluster(null)}>
                    <div className="detail-panel" onClick={(e) => e.stopPropagation()} style={{ width: 500 }}>
                        <div className="detail-header" style={{ marginBottom: 16 }}>
                            <h2>오류 신고 및 재배치</h2>
                            <button className="detail-close" onClick={() => setErrorPanelCluster(null)}>
                                <X style={{ width: 18, height: 18 }} />
                            </button>
                        </div>

                        <div style={{ background: '#f8fafc', padding: 20, borderRadius: 12, marginBottom: 24, border: '1px solid #e2e8f0' }}>
                            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>현재 AI 분류 결과</div>
                            <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>{errorPanelCluster.representative_name}</div>
                            <div style={{ fontSize: 13, color: '#475569' }}>
                                코드: {errorPanelCluster.code || '없음'} | 항목 수: {errorPanelCluster.item_count}개
                            </div>
                        </div>

                        <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 16 }}>이 항목을 어디로 옮길까요?</h3>

                        <div style={{ marginBottom: 24 }}>
                            <div style={{ position: 'relative', marginBottom: 12 }}>
                                <SearchIcon style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', width: 16, height: 16, color: '#94a3b8' }} />
                                <input
                                    type="text"
                                    placeholder="클러스터 명칭/코드 검색..."
                                    value={searchTargetQuery}
                                    onChange={(e) => setSearchTargetQuery(e.target.value)}
                                    style={{ width: '100%', padding: '12px 16px 12px 36px', borderRadius: 8, border: '1px solid #cbd5e1', outline: 'none' }}
                                />
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                {/* 검색 결과가 있으면 검색 결과 표시, 없으면 AI 추천 후보 표시 */}
                                {(searchTargetQuery ? searchedClusters : candidateClusters).map(c => (
                                    <div
                                        key={c.cluster_id}
                                        className={`target-candidate ${selectedTargetClusterId === c.cluster_id ? 'selected' : ''}`}
                                        onClick={() => setSelectedTargetClusterId(c.cluster_id)}
                                        style={{
                                            padding: 16, borderRadius: 8, border: selectedTargetClusterId === c.cluster_id ? '2px solid #3b82f6' : '1px solid #e2e8f0',
                                            background: selectedTargetClusterId === c.cluster_id ? '#eff6ff' : '#fff', cursor: 'pointer'
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                                            <span style={{ fontWeight: 600, color: '#0f172a' }}>{c.representative_name}</span>
                                            {c.code && <span className="badge badge-gray">{c.code}</span>}
                                        </div>
                                        <div style={{ fontSize: 12, color: '#64748b' }}>항목 {c.item_count}개 | 평균가 {formatCurrency(c.avg_cost)}</div>
                                    </div>
                                ))}

                                {!searchTargetQuery && candidateClusters.length > 0 && (
                                    <div style={{ fontSize: 11, textAlign: 'right', color: '#94a3b8', marginTop: -4 }}>↑ AI 추천 유사 클러스터</div>
                                )}

                                <div
                                    className={`target-candidate new-cluster ${selectedTargetClusterId === 'new' ? 'selected' : ''}`}
                                    onClick={() => setSelectedTargetClusterId('new')}
                                    style={{
                                        padding: 16, borderRadius: 8, border: selectedTargetClusterId === 'new' ? '2px solid #3b82f6' : '1px dashed #cbd5e1',
                                        background: selectedTargetClusterId === 'new' ? '#eff6ff' : '#f8fafc', cursor: 'pointer',
                                        display: 'flex', alignItems: 'center', gap: 8, color: '#3b82f6', fontWeight: 600
                                    }}
                                >
                                    <Plus style={{ width: 18, height: 18 }} /> 독립적인 새 클러스터로 분리 (생성)
                                </div>
                            </div>
                        </div>

                        <div style={{ marginBottom: 32 }}>
                            <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 8 }}>수정 사유 (선택)</h3>
                            <input
                                type="text"
                                placeholder="예: 부위가 다름, 치료 목적이 아님 등"
                                value={reasonInput}
                                onChange={(e) => setReasonInput(e.target.value)}
                                style={{ width: '100%', padding: '12px 16px', borderRadius: 8, border: '1px solid #cbd5e1', outline: 'none' }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: 12 }}>
                            <button className="btn btn-outline" onClick={() => setErrorPanelCluster(null)} style={{ flex: 1, justifyContent: 'center', padding: 14 }}>취소</button>
                            <button
                                className="btn btn-primary"
                                onClick={handleSubmitError}
                                disabled={!selectedTargetClusterId}
                                style={{ flex: 2, justifyContent: 'center', padding: 14, opacity: selectedTargetClusterId ? 1 : 0.5 }}
                            >
                                변경 사항 즉시 반영
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
