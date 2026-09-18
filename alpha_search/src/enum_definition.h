#pragma once

namespace global_const {
  const int accelator_category_count = 8;
  const int accelator_per_server_max = 8;
  const int accelerator_counts = 7;
  const double starvation_upper = 80.;
  const double age_weight = 0.13889;
  const int dp_execution_maximum = 100000;
  const int defragmentation_criteria = 20;
  const int statistics_array_size = 8;
  // 민감도 스윕 대상(docs/KNOB_COST_AND_SENSITIVITY.md) — 기본값은 기존 하드코딩과 동일
  const double r_penalty = 0.1;        // 자원 적합도 감쇠 (job_emulator::adjust_wait_queue)
  const double priority_base = 2.0;    // P = 1/base^j 의 밑
  const int queue_prefix_mult = 3;     // SFQA 재정렬 창 = 서버 수 × 이 값
};

enum class accelator_type : int {
  any = -2, cpu = -1, v100, a30, a100, h100, h200, l4, l40, b200
};


enum class scheduler_type : int {
  mostallocated = 0, compact, round_robin, mcts, fare_share
};

enum class emulation_status : int {
  stop, pause, start
};

enum class distribution_type : int {
  norm, expon, lognorm, gamma, beta, weibull_min, uniform, poisson, chi2
};

enum class gpu_allocation_type : int {
  none, empty, fixed, floating, adjusted
};

enum class gpu_defragmentation_method : int {
  max_space
};

enum statistics {
  min = 0, max, avg, sd, p_25, mid, p_75, p_95 
};