# B200×8 단일노드 실측 (버스트) — blocking-aware 컨트롤러, 나이 승급 활성 조건

> 생성 2026-06-13. 목적: heavy-tail 캠페인(`B200_RESULTS_heavytail.md`)에서 `submit-clamp`
> 균일 도착이 **에이징을 FIFO로 퇴화**시킨 한계를, **버스트 도착 보존 + blocking-aware 해제
> + 도착-순번(counter) 나이**로 메워 **나이 승급이 실제로 활성인 첫 실측**을 얻는 것.
> 컨트롤러 수정: `policy_controller.py` (commit b027355, main 30da294 동기). **`paper/sn-article.tex` 미수정.**
> 로그: `results/b200_runs_burst/`. raw: `/raid/squad/runs/b_*/` (저장소 외부).

## 0. 실 서버 / 레짐 형성
- 실 NVIDIA B200×8 노드, K8s v1.31. 6 run × 500잡 = 3,000 실 Pod.
- 버스트 트레이스: `philly_sample500_burst40.csv` = 원 도착 패턴의 arrival만 /40 압축(κ=30 추가 적용 → 도착 span ≈996s), **submit-clamp 0**(버스트 보존). peak **12× capacity** (균일 캠페인 3.6× 대비), 대기 큐 **440개**(균일 ~180 대비 2.4×) — **깊은 버스트 백로그 = 나이 승급 활성 조건** 형성 확인.

## 1. 예측 검증 (핵심)

로컬 리플레이 예측: blocking+counter p1≈93·lt50≈0 / greedy p1≈3.8·lt50≈5.

| 정책 | 예측 p1 | 실측 p1 | 예측 lt50 | 실측 lt50 | 판정 |
|---|--:|--:|--:|--:|---|
| blocking+counter (Δ5) | ≈93 | **82.8** | ≈0 | **0.0%** | ✅ 같은 공정 영역 |
| greedy+wall (대조) | ≈3.8 | **3.8** | ≈5 | **5.0%** | ✅ 정확 일치 |

→ **blocking-aware 해제 + counter 나이가 버스트 과부하에서 아사를 예방**(lt50 0%, p1 82.8)하고, greedy(옛 거동)는 아사(p1 3.8). **균일-도착 퇴화 한계를 정면 해소** — 나이 승급이 활성인 조건에서 검증됨.

## 2. 전체 결과 (6 run)

trace-arrival 기준(=물리적 도착). **trace·wall 두 기준이 모든 run에서 동일**(submit-clamp 0 → wall≈trace 검증).

| run | 정책/플래그 | q_p50 | q_max | BSLD_p50 | fair | **lt50%↓** | **p1↑** | alloc |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| `b_auto_block` | SAFA blocking+counter Δ5 | 1927 | 3283 | 115 | 99.4 | 0.0 | **82.8** | 59% |
| `b_auto_greedy` | SAFA greedy+wall | 474 | 2250 | 27 | 94.4 | 5.0 | **3.8** | 81% |
| `b_auto_d1` | SAFA blocking+counter Δ1 | 443 | 2877 | 37 | 93.0 | 4.0 | **40.1** | 66% |
| `b_fifo` | FIFO blocking | 1784 | 3302 | 120 | 99.4 | 0.2 | **84.2** | 59% |
| `b_auto_block_r2` | SAFA blocking+counter 반복 | 1922 | 3292 | 115 | 99.2 | 0.2 | **82.4** | 59% |
| `b_fifo_r2` | FIFO blocking 반복 | 1785 | 3298 | 120 | 99.5 | 0.2 | **89.5** | 59% |

## 3. 분석

**① 반복 변동성 (R4):** blocking p1 82.8/82.4 → **±0.2** (매우 안정). FIFO p1 84.2/89.5 → ±2.7. 둘 다 공정 영역(82~90).

**② Δ(주기) 아티팩트:** Δ=5 p1=82.8 vs Δ=1 p1=40.1. 컨트롤러 주기를 5s→1s로 좁히면 dispatch가 빨라져(q_p50 1927→443, alloc 59→66%) 처리량은 좋아지나 p1은 하락. 즉 Δ=5의 높은 p1엔 *느린 주기가 엄격한 순서를 더 오래 강제한* 몫이 섞여 있다. **다만 두 Δ 모두 greedy(3.8)보다 훨씬 공정** — 핵심 대비(blocking≫greedy)는 주기 무관.

**③ blocking ≈ FIFO:** SAFA blocking(82.8) ≈ FIFO blocking(84.2). 즉 **공정성의 직접 원인은 blocking 해제**(순서 보존)이고 greedy만 무너진다. 단일노드·버스트에서 counter 나이는 도착 순번에 단조라 blocking 하 FIFO 순서와 거의 같은 결과(→ §4 한계).

**④ 콜드 기동 (측정 시도 → 방화벽 차단으로 불가, 정직 보고):** holder 삭제 대신 **노드 미캐시 더미 이미지**(`alpine:3.19`, imagePullPolicy=Always)를 pull시켜 콜드 기동을 재려 했으나, **외부 레지스트리가 방화벽 차단**됨 — 실측 이벤트: `Failed to pull "docker.io/library/alpine:3.19": ... dial tcp auth.docker.io:443: i/o timeout` → ErrImagePull. 즉 holder(로컬 dev, 레지스트리 없음)든 공개 이미지든 **이 노드에선 콜드 pull 자체가 불가**(docker.io 차단). 캐시 기동 1.5–3.5s(\S overhead 기측정) 유효, 콜드 1점은 **레지스트리 도달 가능 환경**이 선행돼야 함(향후 과제). 테스트 pod는 측정 후 삭제.

## 4. 시뮬 경향과의 일치성 — 판정

**확증.** 버스트+blocking+counter 조건에서 **나이 승급이 활성화돼 아사를 예방**(lt50 0%, p1 82.8)하고 greedy는 붕괴(p1 3.8) — 예측 대비를 실측이 재현. heavy-tail 캠페인의 "에이징=FIFO 퇴화" 한계를 버스트 도착으로 해소했고, 깊은 버스트 큐(440)가 승급 활성 조건임을 확인했다.

**정직한 단서 — SAFA의 *고유* 가치는 여전히 미입증:**
- 단일노드·버스트에서 counter 나이는 도착 순번에 단조라 **blocking 하에서 SAFA(p1 82.8)와 FIFO(p1 84.2)가 사실상 동등**하다. 즉 입증된 것은 *"blocking 해제가 아사를 막는다"*이지, *"SAFA의 나이 승급이 단순 FIFO보다 낫다"*가 아니다.
- SAFA가 FIFO를 능가하는 지점(공정성을 지키면서 *중앙 대기/효율*을 개선 — 또래 대비 굶주린 큰 잡을 선별 승급해 효율 손실 없이 아사만 제거)은 **다중노드·단편화 레짐**에서만 드러나며, 시뮬(256~1024 GPU)이 그 축을 담당한다.
- 단일노드는 배치/단편화 아사가 원리적으로 부재하고, n=500이라 p1은 표본 변동이 있다(주 지표 lt50%·fair_mean 병행).
- Δ=1(현실적 운영점, alloc 66%)에서 p1=40.1로 Δ=5(82.8)보다 낮다 — 운영 주기에 따라 공정성-효율 트레이드오프가 있음.

**종합**: 실 클러스터에서 **(a) blocking-aware 해제가 버스트 과부하 아사를 예방함(greedy 대비 p1 3.8→82.8)을 입증**, **(b) 컨트롤러 수정으로 무튜닝 SAFA가 더는 SJF로 퇴화하지 않음을 확인**. 단 **SAFA의 FIFO 대비 고유 이득은 단일노드 범위 밖(시뮬·다중노드 전담)**임을 명시.

## 5. 재현
```
# 버스트 트레이스: arrival만 /40 (버스트 보존), 그 뒤 κ=30
python -c "import csv;rows=list(csv.DictReader(open('results/philly_sample500_jct2h_window.csv')));[r.update(arrival_time_s=str(float(r['arrival_time_s'])/40)) for r in rows];csv.DictWriter(open('results/philly_sample500_burst40.csv','w',newline=''),fieldnames=rows[0].keys()).writerows([dict(zip(rows[0],rows[0]))]+rows)"
cd squad_ctrl
F="--trace csv --input ../results/philly_sample500_burst40.csv --sample 0 --kappa 30 --min-dur 2 --max-dur 0 --submit-clamp 0 --timeout 7200"
./run_one.sh sfqa-auto b_auto_block "" "$F"                              # blocking+counter (기본)
./run_one.sh sfqa-auto b_auto_greedy "--release greedy --age-mode wall" "$F"
./run_one.sh sfqa-auto b_auto_d1 "--period 1" "$F"
./run_one.sh fifo b_fifo "" "$F"
./run_one.sh sfqa-auto b_auto_block_r2 "" "$F";  ./run_one.sh fifo b_fifo_r2 "" "$F"
/raid/squad/venv/bin/python analyze_b200_burst.py     # → results/b200_burst_summary.csv
```
순서공정성은 trace-arrival 기준(submit-clamp 0 → wall과 동일, 분석기가 둘 다 출력해 검증).
