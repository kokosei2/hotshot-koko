#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hotshot Finder Mobile v1.0
Streamlit 기반 모바일 웹앱

실행 방법:
pip install streamlit
streamlit run hotshot_mobile.py
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Dict, Tuple
import requests
from io import BytesIO
from PIL import Image

# YouTube API
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate
import openpyxl

# ==================== 설정 ====================

logging.basicConfig(level=logging.INFO)
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

SHORTS_DURATION_LIMIT = 180
MAX_RESULTS_TOTAL = 50
DAILY_QUOTA_LIMIT = 10000

QUOTA_COSTS = {
    'search': 100,
    'videos': 1,
    'channels': 1
}

# 20개국 목록
GLOBAL_TOP_COUNTRIES = [
    {'code': 'US', 'name': '미국'},
    {'code': 'IN', 'name': '인도'},
    {'code': 'GB', 'name': '영국'},
    {'code': 'JP', 'name': '일본'},
    {'code': 'KR', 'name': '한국'},
    {'code': 'BR', 'name': '브라질'},
    {'code': 'CA', 'name': '캐나다'},
    {'code': 'DE', 'name': '독일'},
    {'code': 'FR', 'name': '프랑스'},
    {'code': 'AU', 'name': '호주'},
    {'code': 'MX', 'name': '멕시코'},
    {'code': 'ES', 'name': '스페인'},
    {'code': 'IT', 'name': '이탈리아'},
    {'code': 'RU', 'name': '러시아'},
    {'code': 'ID', 'name': '인도네시아'},
    {'code': 'TH', 'name': '태국'},
    {'code': 'VN', 'name': '베트남'},
    {'code': 'PH', 'name': '필리핀'},
    {'code': 'AR', 'name': '아르헨티나'},
    {'code': 'PL', 'name': '폴란드'}
]

COUNTRY_CODE_TO_NAME = {c['code']: c['name'] for c in GLOBAL_TOP_COUNTRIES}

CATEGORY_OPTIONS = {
    '영화/드라마': '1',
    '음악': '10',
    '게임': '20',
    '엔터테인먼트': '24',
    '뉴스': '25',
    '교육': '27',
    '경제': '28',
    '스포츠': '17'
}

# ==================== Streamlit 페이지 설정 ====================

st.set_page_config(
    page_title="Hotshot Finder Mobile",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 모바일 최적화 CSS
st.markdown("""
<style>
    /* 모바일 친화적 스타일 */
    .stButton>button {
        width: 100%;
        height: 50px;
        font-size: 16px;
    }
    .stSelectbox, .stTextInput {
        font-size: 16px;
    }
    /* 결과 카드 */
    .result-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 15px;
        background: white;
    }
    .result-title {
        font-size: 16px;
        font-weight: bold;
        margin-bottom: 8px;
    }
    .result-meta {
        font-size: 14px;
        color: #666;
    }
    .result-stats {
        font-size: 13px;
        color: #0066cc;
        margin-top: 8px;
    }
    /* 반응형 */
    @media (max-width: 768px) {
        .stButton>button {
            height: 60px;
            font-size: 18px;
        }
    }
</style>
""", unsafe_allow_html=True)

# ==================== 세션 상태 초기화 ====================

if 'api_key' not in st.session_state:
    st.session_state.api_key = None
if 'results' not in st.session_state:
    st.session_state.results = []
if 'quota_used' not in st.session_state:
    st.session_state.quota_used = 0

# ==================== 유틸리티 함수 ====================

def parse_duration(duration_str: str) -> int:
    try:
        duration = isodate.parse_duration(duration_str)
        return int(duration.total_seconds())
    except:
        return 0

def format_number(num: int) -> str:
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    return str(num)

def calc_global_score(views: int, likes: int, comments: int, 
                     subscribers: int, hours_since: float) -> float:
    if hours_since <= 0:
        hours_since = 0.1
    
    velocity = views / hours_since
    velocity_score = min(40, (velocity / 10000) * 40)
    
    engagement = (likes + comments * 2) / max(views, 1)
    engagement_score = min(30, (engagement * 100) * 30)
    
    views_score = min(20, (views / 1_000_000) * 20)
    
    if subscribers > 0:
        viewsub_ratio = views / subscribers
        sub_score = min(10, viewsub_ratio * 2)
    else:
        sub_score = 5
    
    total_score = velocity_score + engagement_score + views_score + sub_score
    return round(min(100, total_score), 1)

# ==================== YouTube API 함수 ====================

@st.cache_data(ttl=3600)
def fetch_videos_by_keyword(api_key: str, keyword: str, region_code: str = None) -> List[str]:
    """키워드 검색 (캐싱)"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        published_after = (datetime.utcnow() - timedelta(days=7)).isoformat("T") + "Z"
        
        params = {
            'part': 'snippet',
            'q': keyword,
            'type': 'video',
            'maxResults': MAX_RESULTS_TOTAL,
            'order': 'date',
            'publishedAfter': published_after
        }
        
        if region_code and region_code != 'GLOBAL':
            params['regionCode'] = region_code
        
        request = youtube.search().list(**params)
        response = request.execute()
        
        video_ids = [item['id']['videoId'] for item in response.get('items', []) 
                     if item['id']['kind'] == 'youtube#video']
        
        st.session_state.quota_used += QUOTA_COSTS['search']
        return video_ids
        
    except Exception as e:
        st.error(f"검색 실패: {str(e)}")
        return []

@st.cache_data(ttl=3600)
def fetch_category_videos(api_key: str, category_id: str, region_code: str) -> Tuple[List[str], str]:
    """카테고리 검색"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        request = youtube.videos().list(
            part='snippet,contentDetails',
            chart='mostPopular',
            regionCode=region_code,
            videoCategoryId=category_id,
            maxResults=5
        )
        response = request.execute()
        
        video_ids = [item['id'] for item in response.get('items', [])]
        st.session_state.quota_used += QUOTA_COSTS['videos']
        
        return video_ids, region_code
        
    except Exception as e:
        return [], region_code

@st.cache_data(ttl=3600)
def fetch_stats(api_key: str, video_ids: List[str]) -> Dict[str, dict]:
    """영상 통계 조회"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        stats = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            
            request = youtube.videos().list(
                part='snippet,contentDetails,statistics',
                id=','.join(batch)
            )
            response = request.execute()
            st.session_state.quota_used += QUOTA_COSTS['videos']
            
            for item in response.get('items', []):
                video_id = item['id']
                snippet = item.get('snippet', {})
                content = item.get('contentDetails', {})
                statistics = item.get('statistics', {})
                
                stats[video_id] = {
                    'title': snippet.get('title', ''),
                    'channel_title': snippet.get('channelTitle', ''),
                    'channel_id': snippet.get('channelId', ''),
                    'published_at': snippet.get('publishedAt', ''),
                    'duration': parse_duration(content.get('duration', 'PT0S')),
                    'views': int(statistics.get('viewCount', 0)),
                    'likes': int(statistics.get('likeCount', 0)),
                    'comments': int(statistics.get('commentCount', 0)),
                    'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get('url', '')
                }
        
        return stats
        
    except Exception as e:
        st.error(f"통계 조회 실패: {str(e)}")
        return {}

@st.cache_data(ttl=3600)
def fetch_subscriber_counts(api_key: str, channel_ids: List[str]) -> Dict[str, int]:
    """구독자 수 조회"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        subscribers = {}
        unique_ids = list(set(channel_ids))
        
        for i in range(0, len(unique_ids), 50):
            batch = unique_ids[i:i+50]
            
            request = youtube.channels().list(
                part='statistics',
                id=','.join(batch)
            )
            response = request.execute()
            st.session_state.quota_used += QUOTA_COSTS['channels']
            
            for item in response.get('items', []):
                channel_id = item['id']
                stats = item.get('statistics', {})
                subscribers[channel_id] = int(stats.get('subscriberCount', 0))
        
        return subscribers
        
    except Exception as e:
        return {}

# ==================== 메인 UI ====================

# 헤더
st.title("🔥 Hotshot Finder Mobile")
st.caption("YouTube 떡상 영상 탐지기 - 모바일 버전")

# 사이드바 - 설정
with st.sidebar:
    st.header("⚙️ 설정")
    
    # API 키 입력
    api_key = st.text_input(
        "YouTube API 키",
        type="password",
        value=st.session_state.api_key or "",
        help="Google Cloud Console에서 발급받은 API 키를 입력하세요"
    )
    
    if api_key:
        st.session_state.api_key = api_key
        st.success("✅ API 키 설정됨")
    
    st.divider()
    
    # 쿼터 표시
    remaining = DAILY_QUOTA_LIMIT - st.session_state.quota_used
    st.metric("남은 쿼터", f"{remaining:,} / {DAILY_QUOTA_LIMIT:,}")
    
    if st.button("쿼터 리셋"):
        st.session_state.quota_used = 0
        st.rerun()
    
    st.divider()
    
    # 지역 선택
    region_options = ["전세계 (ALL)"] + [f"{c['name']} ({c['code']})" for c in GLOBAL_TOP_COUNTRIES]
    region = st.selectbox("지역 선택", region_options)
    
    # 정렬 옵션
    st.divider()
    sort_option = st.selectbox(
        "정렬",
        [
            "떡상점수 (높은순)",
            "조회수 (많은순)",
            "시간당 조회수 (높은순)",
            "업로드 시간 (최신순)"
        ]
    )

# 메인 영역 - 검색
st.header("🔍 검색")

tab1, tab2 = st.tabs(["키워드 검색", "카테고리 검색"])

with tab1:
    keyword = st.text_input("검색할 키워드를 입력하세요", placeholder="예: Minecraft, 먹방, ASMR")
    
    if st.button("🔍 키워드 검색", type="primary", use_container_width=True):
        if not st.session_state.api_key:
            st.error("⚠️ API 키를 먼저 입력하세요")
        elif not keyword:
            st.warning("키워드를 입력하세요")
        else:
            with st.spinner("검색 중..."):
                # 지역 코드 추출
                region_code = "GLOBAL" if region.startswith("전세계") else region.split("(")[1].split(")")[0]
                
                # 검색
                video_ids = fetch_videos_by_keyword(
                    st.session_state.api_key, 
                    keyword, 
                    None if region_code == "GLOBAL" else region_code
                )
                
                if not video_ids:
                    st.info("검색 결과가 없습니다.")
                else:
                    st.success(f"✅ {len(video_ids)}개 영상 발견")
                    
                    # 통계 조회
                    with st.spinner("영상 정보 수집 중..."):
                        stats = fetch_stats(st.session_state.api_key, video_ids)
                        
                        channel_ids = [s['channel_id'] for s in stats.values()]
                        subscribers = fetch_subscriber_counts(st.session_state.api_key, channel_ids)
                    
                    # 결과 처리
                    results = []
                    now = datetime.utcnow()
                    
                    for video_id, data in stats.items():
                        try:
                            published = datetime.strptime(data['published_at'], '%Y-%m-%dT%H:%M:%SZ')
                            hours_since = (now - published).total_seconds() / 3600
                            
                            channel_subs = subscribers.get(data['channel_id'], 0)
                            velocity = data['views'] / max(hours_since, 0.1)
                            score = calc_global_score(
                                data['views'], data['likes'], data['comments'],
                                channel_subs, hours_since
                            )
                            
                            results.append({
                                'video_id': video_id,
                                'title': data['title'],
                                'channel_title': data['channel_title'],
                                'views': data['views'],
                                'likes': data['likes'],
                                'comments': data['comments'],
                                'subscribers': channel_subs,
                                'thumbnail': data['thumbnail'],
                                'duration': data['duration'],
                                'hours_since': hours_since,
                                'velocity': velocity,
                                'score': score,
                                'search_country': region_code
                            })
                        except:
                            pass
                    
                    st.session_state.results = results

with tab2:
    category = st.selectbox("카테고리 선택", list(CATEGORY_OPTIONS.keys()))
    
    if st.button("📺 카테고리 검색", type="primary", use_container_width=True):
        if not st.session_state.api_key:
            st.error("⚠️ API 키를 먼저 입력하세요")
        else:
            category_id = CATEGORY_OPTIONS[category]
            
            with st.spinner("전세계 20개국 검색 중..."):
                all_video_ids = []
                video_country_map = {}
                
                # 진행률 표시
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, country in enumerate(GLOBAL_TOP_COUNTRIES):
                    status_text.text(f"수집 중: {country['name']} ({idx+1}/20)")
                    progress_bar.progress((idx + 1) / 20)
                    
                    video_ids, _ = fetch_category_videos(
                        st.session_state.api_key,
                        category_id,
                        country['code']
                    )
                    
                    for vid in video_ids:
                        if vid not in video_country_map:
                            video_country_map[vid] = country['code']
                            all_video_ids.append(vid)
                
                status_text.text("완료!")
                
                if not all_video_ids:
                    st.info("검색 결과가 없습니다.")
                else:
                    st.success(f"✅ {len(all_video_ids)}개 영상 발견 (20개국)")
                    
                    # 통계 조회
                    with st.spinner("영상 정보 수집 중..."):
                        stats = fetch_stats(st.session_state.api_key, all_video_ids[:50])
                        channel_ids = [s['channel_id'] for s in stats.values()]
                        subscribers = fetch_subscriber_counts(st.session_state.api_key, channel_ids)
                    
                    # 결과 처리
                    results = []
                    now = datetime.utcnow()
                    
                    for video_id, data in stats.items():
                        try:
                            published = datetime.strptime(data['published_at'], '%Y-%m-%dT%H:%M:%SZ')
                            hours_since = (now - published).total_seconds() / 3600
                            
                            channel_subs = subscribers.get(data['channel_id'], 0)
                            velocity = data['views'] / max(hours_since, 0.1)
                            score = calc_global_score(
                                data['views'], data['likes'], data['comments'],
                                channel_subs, hours_since
                            )
                            
                            results.append({
                                'video_id': video_id,
                                'title': data['title'],
                                'channel_title': data['channel_title'],
                                'views': data['views'],
                                'likes': data['likes'],
                                'comments': data['comments'],
                                'subscribers': channel_subs,
                                'thumbnail': data['thumbnail'],
                                'duration': data['duration'],
                                'hours_since': hours_since,
                                'velocity': velocity,
                                'score': score,
                                'search_country': video_country_map.get(video_id, 'UNKNOWN')
                            })
                        except:
                            pass
                    
                    st.session_state.results = results

# 결과 표시
st.divider()
st.header("📊 검색 결과")

if st.session_state.results:
    # 정렬
    results = st.session_state.results.copy()
    
    if "떡상점수" in sort_option:
        results.sort(key=lambda x: x['score'], reverse=True)
    elif "조회수" in sort_option:
        results.sort(key=lambda x: x['views'], reverse=True)
    elif "시간당" in sort_option:
        results.sort(key=lambda x: x['velocity'], reverse=True)
    elif "업로드" in sort_option:
        results.sort(key=lambda x: x['hours_since'], reverse=False)
    
    st.caption(f"총 {len(results)}개 영상")
    
    # Excel 다운로드
    df = pd.DataFrame([{
        '순위': idx + 1,
        '제목': r['title'],
        '채널': r['channel_title'],
        '검색국가': COUNTRY_CODE_TO_NAME.get(r['search_country'], r['search_country']),
        '형식': 'Shorts' if r['duration'] <= SHORTS_DURATION_LIMIT else '일반',
        '조회수': r['views'],
        '좋아요': r['likes'],
        '떡상점수': r['score'],
        'URL': f"https://www.youtube.com/watch?v={r['video_id']}"
    } for idx, r in enumerate(results)])
    
    st.download_button(
        label="📥 Excel 다운로드",
        data=df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig'),
        file_name=f"hotshot_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True
    )
    
    st.divider()
    
    # 결과 카드 표시
    for idx, result in enumerate(results, 1):
        with st.container():
            col1, col2 = st.columns([1, 3])
            
            with col1:
                # 썸네일
                try:
                    response = requests.get(result['thumbnail'], timeout=5)
                    img = Image.open(BytesIO(response.content))
                    st.image(img, use_container_width=True)
                except:
                    st.info("썸네일 없음")
            
            with col2:
                # 제목
                st.markdown(f"**#{idx} {result['title']}**")
                
                # 메타정보
                country_name = COUNTRY_CODE_TO_NAME.get(result['search_country'], result['search_country'])
                format_text = "Shorts" if result['duration'] <= SHORTS_DURATION_LIMIT else "일반"
                
                st.caption(f"채널: {result['channel_title']} | 검색국가: {country_name}")
                st.caption(f"형식: {format_text} | 조회수: {format_number(result['views'])} | 좋아요: {format_number(result['likes'])}")
                
                # 떡상 정보
                st.markdown(f"**떡상 점수: {result['score']}/100** | 시간당 조회수: {format_number(int(result['velocity']))} | {result['hours_since']:.1f}시간 전")
                
                # 버튼
                video_url = f"https://www.youtube.com/watch?v={result['video_id']}"
                st.link_button("▶️ 영상 보기", video_url, use_container_width=True)
            
            st.divider()
else:
    st.info("검색을 시작하세요")

# 푸터
st.divider()
st.caption("Hotshot Finder Mobile v1.0 | Made with Streamlit")
