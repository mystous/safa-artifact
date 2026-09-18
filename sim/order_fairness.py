"""순서 공정성(Order Fairness) — 큐(도착) 순서 vs 실제 처리 순서의 어긋남.

정의: 잡을 도착순 정렬 → 그 순서대로 '시작시각(place_time)' 나열 → 역전(inversion) 수 계산.
  역전 = (도착 i < j) 인데 (시작 i > 시작 j) — 늦게 온 잡이 먼저 처리된 쌍.
  공정성 = 100 × (1 − inv / C(n,2)).   FIFO=100, 완전 역순=0.
역전 수는 merge-sort 분할정복으로 O(n log n) (n=111k에서 O(n²) 불가).

완료(finish) 기준 버전도 함께 계산(처리 '완료' 순서 어긋남).

실행: order_fairness.py <pj_dir_with_arrival_start>  또는 시뮬 재실행 모드.
"""
import sys


def count_inversions(seq):
    """seq의 역전 수(왼쪽이 오른쪽보다 큰 쌍)를 merge-sort로 O(n log n)에 계산."""
    def sort_count(a):
        n = len(a)
        if n <= 1:
            return a, 0
        m = n // 2
        left, cl = sort_count(a[:m])
        right, cr = sort_count(a[m:])
        merged = []
        i = j = inv = 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:          # 같으면 역전 아님(stable)
                merged.append(left[i]); i += 1
            else:
                merged.append(right[j]); j += 1
                inv += len(left) - i          # left의 남은 전부가 right[j]보다 큼
        merged += left[i:]; merged += right[j:]
        return merged, cl + cr + inv
    _, total = sort_count(list(seq))
    return total


def order_fairness(jobs):
    """jobs: [(arrival, start, finish)] → (시작기준 공정성, 완료기준 공정성, 역전수)."""
    n = len(jobs)
    if n < 2:
        return 100.0, 100.0, 0
    maxinv = n * (n - 1) / 2
    by_arr = sorted(range(n), key=lambda k: (jobs[k][0], k))   # 도착순 인덱스
    start_seq = [jobs[k][1] for k in by_arr]                   # 도착순대로 시작시각
    fin_seq = [jobs[k][2] for k in by_arr]
    inv_s = count_inversions(start_seq)
    inv_f = count_inversions(fin_seq)
    return 100.0 * (1 - inv_s / maxinv), 100.0 * (1 - inv_f / maxinv), inv_s


def per_job_overtaken(jobs):
    """잡별 '추월당한 수' = 나보다 늦게 도착했는데 나보다 먼저 시작된 잡의 수.
    도착순 인덱스 i의 잡에 대해, start[i]보다 작은 start[j](j>i, 즉 늦게 도착)의 개수.
    merge-sort로 O(n log n). 반환: 도착순 잡별 overtaken 리스트.
    """
    n = len(jobs)
    by_arr = sorted(range(n), key=lambda k: (jobs[k][0], k))
    starts = [jobs[k][1] for k in by_arr]          # 도착순대로 시작시각
    overtaken = [0] * n
    # merge-sort: 오른쪽(늦게도착) 원소가 왼쪽(먼저도착) 원소보다 먼저 시작되면,
    # 그 왼쪽 원소들이 '추월당함'. 인덱스 추적하며 카운트.
    idx = list(range(n))    # starts 상의 위치
    def sort_count(lo, hi):
        if hi - lo <= 1:
            return
        mid = (lo + hi) // 2
        sort_count(lo, mid); sort_count(mid, hi)
        merged = []; i, j = lo, mid
        right_passed = 0     # 지금까지 merged로 빠져나간 오른쪽(늦게도착) 개수
        while i < mid and j < hi:
            if starts[idx[i]] <= starts[idx[j]]:
                # 왼쪽 원소가 먼저 시작 → 이 왼쪽 원소를 추월한 오른쪽 = right_passed개
                overtaken[idx[i]] += right_passed
                merged.append(idx[i]); i += 1
            else:
                right_passed += 1
                merged.append(idx[j]); j += 1
        while i < mid:
            overtaken[idx[i]] += right_passed
            merged.append(idx[i]); i += 1
        while j < hi:
            merged.append(idx[j]); j += 1
        idx[lo:hi] = merged
    sort_count(0, n)
    # overtaken은 starts 인덱스(=도착순 by_arr 위치) 기준 → 원 잡 매핑
    return [overtaken[p] for p in range(n)], by_arr


def per_job_score(jobs):
    """잡별 순서공정성 점수(0~100). 100=아무도 안 추월(완전 공정), 0=뒤 잡 전부가 추월.
    점수 = 100·(1 − 추월당한수 / 나보다_늦게도착한_잡수). 마지막 도착 잡(뒤 잡 0)은 100.
    """
    n = len(jobs)
    ov, by_arr = per_job_overtaken(jobs)   # 원 잡 인덱스 기준 추월수
    # 도착순위: by_arr[r] = 도착 r번째 잡의 원인덱스. later_count(원인덱스) = n-1-도착순위
    later = [0] * n
    for rank, orig in enumerate(by_arr):
        later[orig] = n - 1 - rank
    scores = []
    for k in range(n):
        L = later[k]
        # 동일 도착시각 타이브레이크로 ov가 L을 미세 초과할 수 있어 0으로 clamp.
        scores.append(100.0 if L == 0 else max(0.0, 100.0 * (1 - ov[k] / L)))
    return scores


if __name__ == "__main__":
    import sys as _s
    if len(_s.argv) > 1 and _s.argv[1] == "score":
        fifo = [(i, i, i) for i in range(5)]
        rev = [(i, 5 - i, 5 - i) for i in range(5)]
        print("FIFO 점수:", [round(x) for x in per_job_score(fifo)], "(전부 100)")
        print("역순 점수:", [round(x) for x in per_job_score(rev)], "(0,0,0,0,100)")
        _s.exit()
    # 검증: 완전 FIFO=100, 완전 역순=0
    fifo = [(i, i, i) for i in range(100)]            # 도착=시작=완료 순서 동일
    rev = [(i, 100 - i, 100 - i) for i in range(100)]  # 늦게 온 게 먼저
    print("FIFO:", order_fairness(fifo)[:2], "(100,100 기대)")
    print("역순:", order_fairness(rev)[:2], "(0,0 기대)")
