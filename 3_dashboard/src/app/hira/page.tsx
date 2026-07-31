'use client';

import { useState } from 'react';
import { DatabaseZap, Search as SearchIcon, AlertCircle } from 'lucide-react';
import { HOSPITAL_COLORS } from '@/lib/types';
import { formatCurrency, formatNumber } from '@/lib/utils';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';

// Mock Data for HIRA
const MOCK_HIRA_DATA = [
    { code: 'HZ228', name: 'F-18 플루트메타몰 뇌양전자단층촬영', webAvg: 560000, hiraAvg: 540000, match: '일치' },
    { code: 'TX009', name: '디지털 치료기기를 이용한 만성 불면증 환자의 인지행동치료', webAvg: 235000, hiraAvg: 235000, match: '일치' },
    { code: 'MZ012', name: '초음파 유도하 하이푸 시술', webAvg: 850000, hiraAvg: 720000, match: '불일치 (웹 데이터 고평가)' },
    { code: 'NA234', name: '다빈치 로봇 수술 (전립선)', webAvg: 11000000, hiraAvg: 12500000, match: '불일치 (HIRA 데이터 고평가)' },
];

export default function HiraPage() {
    const [searchQuery, setSearchQuery] = useState('');

    const filteredData = MOCK_HIRA_DATA.filter(item =>
        item.name.includes(searchQuery) || item.code.includes(searchQuery)
    );

    return (
        <div>
            <div className="page-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <DatabaseZap style={{ width: 28, height: 28, color: '#3b82f6' }} />
                    <div>
                        <h1>HIRA API 데이터 비교</h1>
                        <p>심평원 Open API 데이터와 웹 크롤링 데이터를 비교 검증합니다</p>
                    </div>
                </div>
            </div>

            <div className="card" style={{ marginBottom: 24, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
                <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                    <AlertCircle style={{ width: 20, height: 20, color: '#f59e0b', flexShrink: 0, marginTop: 2 }} />
                    <div>
                        <h3 style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>데이터 소스 안내</h3>
                        <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>
                            이 페이지는 향후 심평원 API 연동 시 사용할 UI의 프로토타입입니다. <br />
                            현재 설정된 데이터베이스의 웹 크롤링 데이터와 심평원에서 공식 제공하는 비급여 진료비 정보를 조회 및 대조하여,
                            항목 누락이나 가격 불일치 여부를 모니터링할 수 있습니다.
                        </p>
                    </div>
                </div>
            </div>

            <div className="card">
                <div className="cluster-list-header">
                    <div className="card-title" style={{ marginBottom: 0 }}>데이터 비교 목록</div>
                    <div className="filter-bar">
                        <div style={{ position: 'relative' }}>
                            <SearchIcon style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 16, height: 16, color: '#94a3b8' }} />
                            <input
                                type="text"
                                placeholder="명칭/코드 검색..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                style={{ paddingLeft: 32, width: 220 }}
                            />
                        </div>
                    </div>
                </div>

                <div className="data-table-wrapper">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>코드</th>
                                <th>명칭</th>
                                <th style={{ background: '#eff6ff' }}>웹 크롤링 평균</th>
                                <th style={{ background: '#f0fdf4' }}>HIRA API 평균</th>
                                <th>차이</th>
                                <th>상태</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredData.map(item => {
                                const diff = item.webAvg - item.hiraAvg;
                                const diffPercent = item.hiraAvg > 0 ? (Math.abs(diff) / item.hiraAvg) * 100 : 0;
                                return (
                                    <tr key={item.code}>
                                        <td style={{ fontSize: 12, color: '#64748b' }}>{item.code}</td>
                                        <td style={{ fontWeight: 500, color: '#0f172a' }}>{item.name}</td>
                                        <td style={{ background: '#f8fafc' }}>{formatCurrency(item.webAvg)}</td>
                                        <td style={{ background: '#f8fafc' }}>{formatCurrency(item.hiraAvg)}</td>
                                        <td style={{ color: diff > 0 ? '#dc2626' : diff < 0 ? '#2563eb' : '#64748b', fontWeight: 600 }}>
                                            {diff === 0 ? '-' : (diff > 0 ? '+' : '') + formatCurrency(diff)}
                                            {diff !== 0 && <span style={{ fontSize: 11, marginLeft: 4 }}>({diffPercent.toFixed(1)}%)</span>}
                                        </td>
                                        <td>
                                            <span className={`badge ${item.match === '일치' ? 'badge-green' : 'badge-orange'
                                                }`}>
                                                {item.match}
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
