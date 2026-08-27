from pathlib import Path
from urllib.parse import urlencode

from trendspy import Trends
import pandas as pd
import json
import time
import random

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _explore_page_url(keyword, geo='', timeframe='today 12-m'):
    """浏览器里可打开的 Google Trends 页面。"""
    params = {'q': keyword, 'date': timeframe, 'hl': 'zh-CN'}
    if geo:
        params['geo'] = geo
    return 'https://trends.google.com/trends/explore?' + urlencode(params)


def get_related_queries(keyword, geo='', timeframe='today 12-m'):
    """获取关键词的相关查询数据，带请求限制。"""
    while True:
        tr = Trends(hl='zh-CN')

        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

        headers = {
            'referer': 'https://www.google.com/',
            'User-Agent': random.choice(user_agents),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }

        try:
            request_limiter.wait_if_needed()

            delay = random.uniform(1, 3)
            time.sleep(delay)

            print(f"Google Trends 页面: {_explore_page_url(keyword, geo, timeframe)}")
            related_data = tr.related_queries(
                keyword,
                headers=headers,
                geo=geo,
                timeframe=timeframe
            )
            print(f"成功获取数据！")
            return related_data

        except Exception as e:
            error_msg = str(e)
            print(f"尝试获取数据时出错: {error_msg}")

            if "API quota exceeded" in error_msg:
                wait_time = random.uniform(300, 360)
                print(f"API配额超限，等待 {wait_time:.1f} 秒后重试...")
                time.sleep(wait_time)
                continue

            if "'NoneType' object has no attribute 'raise_for_status'" in error_msg:
                wait_time = random.uniform(60, 120)
                print(f"请求返回为空，等待 {wait_time:.1f} 秒后重试...")
                time.sleep(wait_time)
                continue

            raise


def get_interest_over_time(keyword, geo='', timeframe='today 12-m'):
    """获取关键词热度随时间变化的趋势（Google Trends 0–100 相对热度）。"""
    while True:
        tr = Trends(hl='zh-CN')

        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]

        headers = {
            'referer': 'https://www.google.com/',
            'User-Agent': random.choice(user_agents),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }

        try:
            request_limiter.wait_if_needed()

            delay = random.uniform(1, 3)
            time.sleep(delay)

            print(f"Google Trends 页面: {_explore_page_url(keyword, geo, timeframe)}")
            timeline = tr.interest_over_time(
                keyword,
                headers=headers,
                geo=geo,
                timeframe=timeframe
            )
            print(f"成功获取热度趋势数据！")
            return timeline

        except Exception as e:
            error_msg = str(e)
            print(f"尝试获取热度趋势时出错: {error_msg}")

            if "API quota exceeded" in error_msg:
                wait_time = random.uniform(300, 360)
                print(f"API配额超限，等待 {wait_time:.1f} 秒后重试...")
                time.sleep(wait_time)
                continue

            if "'NoneType' object has no attribute 'raise_for_status'" in error_msg:
                wait_time = random.uniform(60, 120)
                print(f"请求返回为空，等待 {wait_time:.1f} 秒后重试...")
                time.sleep(wait_time)
                continue

            raise


def batch_get_queries(keywords, geo='', timeframe='today 12-m', delay_between_queries=5):
    """批量获取多个关键词的数据，带间隔控制。"""
    results = {}

    for keyword in keywords:
        try:
            print(f"\n正在查询关键词: {keyword}")
            results[keyword] = get_related_queries(keyword, geo, timeframe)

            if keyword != keywords[-1]:
                delay = delay_between_queries + random.uniform(0, 2)
                print(f"等待 {delay:.1f} 秒后继续下一个查询...")
                time.sleep(delay)

        except Exception as e:
            print(f"获取 {keyword} 的数据失败: {str(e)}")
            results[keyword] = None
            time.sleep(10)

    return results


def save_related_queries(keyword, related_data, directory=None):
    """保存相关查询数据到 JSON 文件，默认写入项目根目录 data/。"""
    if not related_data:
        return

    output_dir = Path(directory) if directory else DEFAULT_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    json_data = {
        'keyword': keyword,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'related_queries': {
            'top': related_data['top'].to_dict(orient='records') if isinstance(related_data.get('top'), pd.DataFrame) else related_data.get('top'),
            'rising': related_data['rising'].to_dict(orient='records') if isinstance(related_data.get('rising'), pd.DataFrame) else related_data.get('rising')
        }
    }

    filepath = output_dir / f"related_queries_{keyword}_{timestamp}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return str(filepath)


def print_related_queries(related_data):
    """打印相关查询词数据。"""
    if not related_data:
        print("没有相关查询数据")
        return

    print("\n相关查询词统计:")
    print("=" * 50)

    if 'top' in related_data and related_data['top'] is not None:
        print("\n热门查询:")
        print("-" * 30)
        df = related_data['top']
        if isinstance(df, pd.DataFrame):
            for _, row in df.iterrows():
                print(f"- {row['query']:<30} (相关度: {row['value']})")

    if 'rising' in related_data and related_data['rising'] is not None:
        print("\n上升趋势查询:")
        print("-" * 30)
        df = related_data['rising']
        if isinstance(df, pd.DataFrame):
            for _, row in df.iterrows():
                print(f"- {row['query']:<30} (增长: {row['value']})")


def _timeline_to_records(timeline):
    """把热度趋势 DataFrame 转成可 JSON 序列化的记录列表。"""
    if timeline is None or not isinstance(timeline, pd.DataFrame) or timeline.empty:
        return []

    df = timeline.reset_index()
    records = []
    for _, row in df.iterrows():
        record = {}
        for col, val in row.items():
            if pd.isna(val):
                record[str(col)] = None
            elif isinstance(val, pd.Timestamp):
                record[str(col)] = val.isoformat()
            elif hasattr(val, 'item'):
                record[str(col)] = val.item()
            else:
                record[str(col)] = val
        records.append(record)
    return records


def save_interest_over_time(keyword, timeline, directory=None, geo='', timeframe=''):
    """保存热度随时间变化数据到 JSON，默认写入项目根目录 data/。"""
    records = _timeline_to_records(timeline)
    if not records:
        return

    output_dir = Path(directory) if directory else DEFAULT_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    json_data = {
        'keyword': keyword,
        'geo': geo,
        'timeframe': timeframe,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'interest_over_time': records,
    }

    filepath = output_dir / f"interest_over_time_{keyword}_{timestamp}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return str(filepath)


def print_interest_over_time(timeline, keyword=None, max_rows=20):
    """打印关键词热度随时间变化的趋势。"""
    if timeline is None or not isinstance(timeline, pd.DataFrame) or timeline.empty:
        print("没有热度趋势数据")
        return

    title = f"「{keyword}」热度随时间变化" if keyword else "热度随时间变化"
    print(f"\n{title}:")
    print("=" * 50)
    print(f"数据点数: {len(timeline)}")

    value_cols = [c for c in timeline.columns if c != 'isPartial']
    if value_cols:
        series = timeline[value_cols[0]]
        peak_idx = series.idxmax()
        print(f"峰值: {series.max()} @ {peak_idx}")
        print(f"最近: {series.iloc[-1]} @ {timeline.index[-1]}")

    print("-" * 50)
    preview = timeline.tail(max_rows)
    for ts, row in preview.iterrows():
        parts = [f"{col}={row[col]}" for col in timeline.columns]
        print(f"{ts}  {', '.join(parts)}")


def _interest_series(timeline):
    """取出热度数值序列，尽量去掉尚未完整的最后一点。"""
    if timeline is None or not isinstance(timeline, pd.DataFrame) or timeline.empty:
        return None

    df = timeline
    if 'isPartial' in df.columns:
        complete = df.loc[~df['isPartial'].fillna(False)]
        if len(complete) >= 8:
            df = complete

    value_cols = [c for c in df.columns if c != 'isPartial']
    if not value_cols:
        return None

    series = pd.to_numeric(df[value_cols[0]], errors='coerce').dropna()
    return series if not series.empty else None


def has_rising_interest(
    timeline,
    min_rel_gain=1.0,
    min_abs_gain=8,
    recent_ratio=0.3,
    min_points=8,
):
    """判断关键词热度是否有明显上升趋势。

    比较序列前半段基线与最近一段均值：近端均值至少达到基线的 2 倍（翻倍），
    且绝对增幅足够、整体斜率为正、近端没有明显回落。

    Returns:
        dict: rising, reason, baseline_mean, recent_mean, abs_gain, rel_gain, slope_lift
    """
    series = _interest_series(timeline)
    if series is None or len(series) < min_points:
        return {
            'rising': False,
            'reason': '数据点不足，无法判断趋势',
            'baseline_mean': None,
            'recent_mean': None,
            'abs_gain': None,
            'rel_gain': None,
            'slope_lift': None,
        }

    values = series.astype(float)
    n = len(values)
    recent_n = max(3, int(n * recent_ratio))
    baseline_n = max(3, n // 2)
    if baseline_n + recent_n > n:
        baseline_n = max(3, n - recent_n)

    baseline_mean = float(values.iloc[:baseline_n].mean())
    recent_mean = float(values.iloc[-recent_n:].mean())
    abs_gain = recent_mean - baseline_mean
    rel_gain = abs_gain / baseline_mean if baseline_mean > 0 else (float('inf') if abs_gain > 0 else 0.0)

    x = pd.Series(range(n), dtype=float)
    y = values.reset_index(drop=True)
    denom = float(((x - x.mean()) ** 2).sum())
    slope = float(((x - x.mean()) * (y - y.mean())).sum() / denom) if denom else 0.0
    slope_lift = slope * (n - 1)

    tail_mean = float(values.iloc[-max(3, recent_n // 2):].mean())
    not_fading = tail_mean >= recent_mean * 0.85

    abs_ok = abs_gain >= min_abs_gain
    rel_ok = rel_gain >= min_rel_gain
    slope_ok = slope_lift > 0

    rising = abs_ok and rel_ok and slope_ok and not_fading
    if rising:
        rel_text = '∞' if rel_gain == float('inf') else f'{rel_gain:.0%}'
        reason = (
            f"近端均值 {recent_mean:.1f} 不低于基线 {baseline_mean:.1f} 的两倍"
            f"（+{abs_gain:.1f}，相对 {rel_text}）"
        )
    elif not rel_ok:
        rel_text = '∞' if rel_gain == float('inf') else f'{rel_gain:.0%}'
        reason = f"未达到翻倍（近端 {recent_mean:.1f} / 基线 {baseline_mean:.1f}，相对 {rel_text}，需至少 {min_rel_gain:.0%}）"
    elif not abs_ok:
        reason = f"绝对增幅不足（{abs_gain:.1f} < {min_abs_gain}）"
    elif not slope_ok:
        reason = "整体斜率为负或持平，不是上升趋势"
    else:
        reason = "近端热度已回落，不像持续上升"

    return {
        'rising': rising,
        'reason': reason,
        'baseline_mean': round(baseline_mean, 2),
        'recent_mean': round(recent_mean, 2),
        'abs_gain': round(abs_gain, 2),
        'rel_gain': None if rel_gain == float('inf') else round(rel_gain, 4),
        'slope_lift': round(slope_lift, 2),
    }


def print_rising_interest(result, keyword=None):
    """打印热度上升判断结果。"""
    label = f"「{keyword}」" if keyword else "该关键词"
    if result.get('rising'):
        print(f"{label}热度有明显上升趋势: {result['reason']}")
    else:
        print(f"{label}热度没有明显上升趋势: {result.get('reason', '')}")


# timeframe 可能的值：
# today 12-m：12个月
# now 1-d：1天
# now 7-d：7天
# now 30-d：30天
# now 90-d：90天
# 日期格式：2024-12-28 2024-12-30
def main():
    keywords = ['game']
    geo = ''
    timeframe = 'now 1-d'
    query_related = False
    query_interest = True
    delay_between_queries = 100

    print("开始批量查询...")
    print(f"地区: {geo if geo else '全球'}")
    print(f"时间范围: {timeframe}")
    print(f"相关查询: {query_related}  热度趋势: {query_interest}")

    try:
        if query_related:
            results = batch_get_queries(
                keywords,
                geo=geo,
                timeframe=timeframe,
                delay_between_queries=delay_between_queries
            )

            for keyword, data in results.items():
                if data:
                    print(f"\n处理 {keyword} 的相关查询:")
                    print_related_queries(data)
                    filename = save_related_queries(keyword, data)
                    print(f"数据已保存到文件: {filename}")
                else:
                    print(f"\n未能获取 {keyword} 的相关查询")

        if query_related and query_interest:
            delay = delay_between_queries + random.uniform(0, 2)
            print(f"\n等待 {delay:.1f} 秒后开始热度趋势查询...")
            time.sleep(delay)

        if query_interest:
            for i, keyword in enumerate(keywords):
                print(f"\n正在查询热度趋势: {keyword}")
                try:
                    timeline = get_interest_over_time(keyword, geo, timeframe)
                    if timeline is not None and not timeline.empty:
                        print_interest_over_time(timeline, keyword)
                        rising = has_rising_interest(timeline)
                        print_rising_interest(rising, keyword)
                        filename = save_interest_over_time(
                            keyword, timeline, geo=geo, timeframe=timeframe
                        )
                        print(f"数据已保存到文件: {filename}")
                    else:
                        print(f"未能获取 {keyword} 的热度趋势")
                except Exception as e:
                    print(f"获取 {keyword} 的热度趋势失败: {e}")

                if i < len(keywords) - 1:
                    delay = delay_between_queries + random.uniform(0, 2)
                    print(f"等待 {delay:.1f} 秒后继续下一个查询...")
                    time.sleep(delay)

    except Exception as e:
        print(f"批量查询过程中出错: {str(e)}")


class RequestLimiter:
    def __init__(self):
        self.requests = []
        self.max_requests_per_min = 30
        self.max_requests_per_hour = 200

    def can_make_request(self):
        """检查是否可以发起新请求。"""
        current_time = time.time()
        self.requests = [t for t in self.requests if current_time - t < 3600]
        recent_min_requests = len([t for t in self.requests if current_time - t < 60])
        recent_hour_requests = len(self.requests)

        if (recent_min_requests >= self.max_requests_per_min or
                recent_hour_requests >= self.max_requests_per_hour):
            return False
        return True

    def add_request(self):
        """记录新的请求。"""
        self.requests.append(time.time())

    def wait_if_needed(self):
        """如果需要，等待直到可以发送请求。"""
        while not self.can_make_request():
            wait_time = random.uniform(5, 10)
            print(f"达到请求限制，等待 {wait_time:.1f} 秒...")
            time.sleep(wait_time)
        self.add_request()


request_limiter = RequestLimiter()

if __name__ == "__main__":
    main()
