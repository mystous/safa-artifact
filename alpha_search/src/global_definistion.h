#pragma once
#include "enum_definition.h"

namespace global_structure {
  struct scheduler_option {
    scheduler_type  scheduler_index = scheduler_type::mostallocated;
    bool            using_preemetion = false;
    bool            scheduleing_with_flavor_option = false;
    bool            working_till_end = true;
    bool            prevent_starvation = false;
    double          svp_upper = global_const::starvation_upper;
    double          age_weight = global_const::age_weight;
    int             reorder_count = global_const::dp_execution_maximum;
    int             preemption_task_window = global_const::defragmentation_criteria;
    // 민감도 스윕용(선택) — config.set 7~9번째 줄. 미지정 시 기존 동작과 동일
    double          r_penalty = global_const::r_penalty;
    double          priority_base = global_const::priority_base;
    int             queue_prefix_mult = global_const::queue_prefix_mult;
  };

  using scheduler_options = struct scheduler_option;
}