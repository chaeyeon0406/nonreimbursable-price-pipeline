// ─── Cluster ───────────────────────────────────────────
export interface Cluster {
    cluster_id: number;
    top_category: string;     // 최상위계층
    mid_category: string;     // 표준_중분류명
    match_method: string;     // '코드매칭' | 'AI클러스터링'
    representative_name: string;
    item_count: number;
    hospital_count: number;
    hospital_list: string[];
    code: string | null;
    avg_cost: number;
    min_cost: number;
    max_cost: number;
    review_status: 'ai_auto' | 'human_confirmed' | 'human_corrected';
}

// ─── Item ──────────────────────────────────────────────
export interface Item {
    id: number;
    hospital: string;
    top_category: string;
    mid_category: string;
    sub_category: string | null;
    name: string;
    code: string | null;
    classification: string | null;
    cost: number;
    note: string | null;
    cluster_id: number;
    match_method: string;
}

// ─── Category Tree ─────────────────────────────────────
export interface MidCategoryInfo {
    cluster_count: number;
    item_count: number;
}

export type CategoryTree = Record<string, Record<string, MidCategoryInfo>>;

// ─── Stats ─────────────────────────────────────────────
export interface Stats {
    total_items: number;
    total_clusters: number;
    multi_hospital_clusters: number;
    pending_review: number;
    by_top_category: Record<string, number>;
    by_match_method: Record<string, number>;
    by_hospital: Record<string, number>;
}

// ─── Feedback Log ──────────────────────────────────────
export interface FeedbackLog {
    id: number;
    item_id: number;
    item_name: string;
    from_cluster_id: number;
    from_cluster_name: string;
    to_cluster_id: number;
    to_cluster_name: string;
    action: 'confirm' | 'reassign' | 'new_cluster';
    reason: string;
    created_by: string;
    created_at: string;
}

// ─── Constants ─────────────────────────────────────────
export const HOSPITAL_COLORS: Record<string, string> = {
    '서울대': '#2563eb',
    '삼성': '#059669',
    '세브란스': '#7c3aed',
    '아산': '#dc2626',
    '서울성모': '#ea580c',
};

export const HOSPITALS = ['서울대', '삼성', '세브란스', '아산', '서울성모'] as const;

export const TOP_CATEGORIES = ['행위', '치료재료', '약제', '제증명수수료'] as const;

export const MATCH_METHOD_COLORS: Record<string, string> = {
    '코드매칭': '#3b82f6',
    'AI클러스터링': '#8b5cf6',
};

export const REVIEW_STATUS_LABELS: Record<string, string> = {
    'ai_auto': 'AI자동',
    'human_confirmed': '사람확인',
    'human_corrected': '사람수정',
};

export const REVIEW_STATUS_COLORS: Record<string, string> = {
    'ai_auto': '#6b7280',
    'human_confirmed': '#10b981',
    'human_corrected': '#f59e0b',
};
