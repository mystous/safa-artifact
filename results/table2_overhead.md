# 시뮬레이터 보정 파라미터 (실측, 2026-06-06)

> 환경: kind 단일노드 + NVIDIA B200×8, holder:dev(캐시), torch 2.11+cu128.
> 용도: 오버헤드 보정 시뮬레이터(`docs/SIMULATOR_DESIGN.md`) 주입값.
> 원본: `/raid/squad/overheads/lifecycle.csv`, `/raid/squad/ptr/ckpt_overhead.csv`.

## 1. K8s 수명주기 오버헤드 (47잡, 4시나리오)

| 파라미터 | 기호 | 값 | 비고 |
|---|---|---|---|
| 스케줄링 지연(용량 有) | `sched_lat` | **0.5 s** | seq/par8/big8 sched_s≈0, 보수적 0.5 |
| 기동(단독) | `startup_solo` | **1.5 s** | seq1 startup p50=1, p90=2 (이미지 캐시됨) |
| 기동(동시 경합) | `startup_busy` | **3.5 s** | par8/par24 startup p50=3, p90=4 |
| 종료(teardown→complete) | `teardown` | **2.5 s** | 전 시나리오 complete_s p50=2~3 |
| 실행 오버헤드 | `exec_ovh` | **0 s** | holder는 연산 없음(sleep 명목치 일치) |
| **잡당 고정 오버헤드** | — | **단독 ~4 s / 경합 ~7 s** | sched_lat+startup+teardown |

**중요**: par24의 sched_s 17~36s는 오버헤드 아님 = **큐잉(용량 대기)**. 시뮬레이터가
정책 로직으로 직접 계산하므로 주입 금지. 고정 오버헤드 = startup+teardown만.

## 2. PTR 이주 다운타임 D (앱레벨 체크포인트)

체크포인트 = 가중치(bf16 2 B/param) + Adam 옵티마이저(fp32 m,v = 8 B/param) = **10 B/param**.

| 모델 | ckpt(GiB) | save(s) | load(s) | 왕복(s) |
|---|---|---|---|---|
| 1B | 9.3 | 11.4 | 5.3 | 16.7 |
| 3B | 27.9 | 31.5 | 16.0 | 47.5 |
| 7B | 65.2 | 78.7 | 37.0 | 115.7 |
| 13B | 121 | 139.9 | 68.1 | 208 |
| 32B/70B | (단일GPU OOM) | — | — | 외삽 |

**처리율 상수(선형, 외삽용)**: `save_bw = 0.85 GiB/s`, `load_bw = 1.75 GiB/s`
(save가 느림 = GPU→CPU→disk 단일 스트림 직렬화).

### D 모델 (시뮬레이터 주입식)
```
ckpt_gib_per_gpu = (params / gpu_count) * 10 / 1024^3      # 샤딩: GPU당 샤드만
D_app = ckpt_gib_per_gpu / 0.85          # save
      + ckpt_gib_per_gpu / 1.75          # load
      + teardown(2.5) + sched_lat(0.5)   # 이주 후 재배치
```
- **샤딩 주의**: 32B/70B는 멀티-GPU 학습 → 각 GPU가 샤드만 동시 저장 ⇒ 다운타임은
  "전체÷N"이 아니라 "샤드 크기 기준". 단일GPU OOM은 측정 한계지 현실 제약 아님.
- 예: 70B를 8-GPU로 → 샤드 ~8.75B → ckpt ~81 GiB/gpu → D ≈ 81/0.85 + 81/1.75 + 3 ≈ 142 s.
- 1-GPU 7B 학습 잡 단독 이주 → D ≈ 116 s.

### D 모델 (투명 C/R, cuda-checkpoint) — 미측정
사용자 직접 실행 승인 대기(외부 바이너리). 예상: 옵티마이저 상태를 디스크 직렬화 없이
프로세스 메모리 이미지로 떠서 앱레벨보다 빠를 가능성. 측정 후 `D_criu`로 대체.

## 3. PTR 손익 판정 (시뮬레이터가 계산)
PTR 이주는 **디프래그 이득(빈 서버 확보로 대기 잡 조기 배치) > Σ D(이주잡)** 일 때만 발동 가치.
δ(DP 상한)·ω(트리거 큐길이)는 이 손익 곡선으로 결정.

## 4. 미측정·확장 시 갱신 필요
- 멀티노드: 노드 간 이주는 네트워크 전송 추가(현재 단일노드라 0). H100 합류 시 측정.
- 추론 잡(vLLM): 가중치 재적재(앱레벨과 유사) + KV캐시 폐기 — 별도 측정.
- 이종 GPU: 처리율은 디스크/PCIe 의존이라 GPU 타입 무관 가정(검증 필요).
