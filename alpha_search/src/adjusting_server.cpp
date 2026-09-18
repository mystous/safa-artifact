#include "pch.h"
#include "adjusting_server.h"

bool adjusting_server::defragementation(int step) {
  int max_full_empty_server = 0;
  int execute_count = 0;

  reconstruct_server_status();
  build_dp_target();
  int empty_server = calcu_full_empty_server();
  optimal_position.clear();
  int expected_empty_server = get_optimal_adjusting_dp(0, max_full_empty_server, execute_count);
  printf("%d - %d, %d\n", step, empty_server, expected_empty_server);
  if (empty_server < expected_empty_server) {
    printf("%d - %d, %d\n", step, empty_server, expected_empty_server);
    adjust_job_allocation();
    return true;
  }
  return false;
}

void adjusting_server::adjust_job_allocation() {
  for (auto&& job_obj : optimal_position) {
    if (-1 == job_obj.target_index) { continue; }
    server_list->at(job_obj.server_index).remove_job(job_obj.job);
    server_list->at(job_obj.target_index).assign_accelator(job_obj.job, job_obj.job->get_accelerator_count());
  }
}

adjusting_server::~adjusting_server() {
  if (nullptr != server_status) {
    delete[] server_status;
    server_status = nullptr;
  }
}

void adjusting_server::build_dp_target() {
  priroried_target_server.clear();
  for (auto&& index : target_server) {
    priroried_target_server.push_back(index);
  }

  sort(priroried_target_server.begin(), priroried_target_server.end(),
    [this](int op1, int op2) {
      return compare_server_priority(op1, op2);
    });
}

void adjusting_server::reconstruct_server_status() {
  job_list.clear();
  target_server.clear();
  target_job.clear();
  if (nullptr != server_status) {
    delete[] server_status;
    server_status = nullptr;
  }

  int i, j;

  server_status = new server_map[server_list->size() * global_const::accelator_per_server_max];
  if (nullptr == server_status) {
    return;
  }

  for (i = 0; i < server_list->size(); ++i) {
    server_entry& server = server_list->at(i);
    string job_id_old = "";
    job_entry* job = nullptr;

    int empty_slot = server.get_avaliable_accelator_count();
    int accelerator_count = server.get_accelerator_count();
    int server_pos = i * global_const::accelator_per_server_max;

    if (0 == empty_slot || empty_slot == accelerator_count) {

      gpu_allocation_type accelerator_status = gpu_allocation_type::empty;
      if (0 == empty_slot) { accelerator_status = gpu_allocation_type::fixed; }
      for (j = 0; j < accelerator_count; ++j) {
        server_status[server_pos + j].status = accelerator_status;
        server_status[server_pos + j].job_id = "";
      }

      for (j = accelerator_count; j < global_const::accelator_per_server_max; ++j) {
        server_status[server_pos + j].status = gpu_allocation_type::none;
        server_status[server_pos + j].job_id = "";
      }

      continue;
    }

    target_server.insert(i);
    for (j = 0; j < global_const::accelator_per_server_max; ++j) {

      server_status[server_pos + j].job_id = "";
      if (j > server.get_accelerator_count() - 1) {
        server_status[server_pos + j].status = gpu_allocation_type::none;
        job_id_old = "";
        job = nullptr;
        continue;
      }

      if (false == server.reserved[j]) {
        server_status[server_pos + j].status = gpu_allocation_type::empty;
        job_id_old = "";
        job = nullptr;
        continue;
      }

      string job_id = server.job_id_for_reserved[j];
      if (job_id_old != job_id) {
        job_id_old = job_id;
        job = get_job_entry(job_id, server.job_list);
        server_status[server_pos + j].job_id = job_id;
        if (job->is_preemtion_possible() && global_const::accelator_per_server_max != job->get_accelerator_count()) {
          job_element new_element(job, i);
          job_list.push_back(new_element);
        }
      }
      server_status[server_pos + j].status = gpu_allocation_type::fixed;

      if (job->is_preemtion_possible())
        server_status[server_pos + j].status = gpu_allocation_type::floating;

      server_status[server_pos + j].job_id = job_id;
    }
  }
}

job_entry* adjusting_server::get_job_entry(string job_id, vector<job_entry*> job_list) {
  for (auto&& job : job_list) {
    if (job->get_job_id() == job_id) {
      return job;
    }
  }

  return nullptr;
}

bool adjusting_server::compare_server_priority(int op1, int op2) {
  server_entry server_1 = server_list->at(op1);
  server_entry server_2 = server_list->at(op2);

  return server_1.get_avaliable_accelator_count() < server_2.get_avaliable_accelator_count();
}

int adjusting_server::get_optimal_adjusting_dp(int recursive_count, int &max_full_empty_server, int &execute_count) {
  vector<job_entry*> rearrange_target;

  if (execute_count > max_execute_number) { return max_full_empty_server; }
  execute_count++;

  string state_key = generate_state_key(recursive_count);
  auto it = memoization_cache.find(state_key);
  if (it != memoization_cache.end()) {
    return it->second;
  }

  if (0 == recursive_count) {
    memoization_cache.clear();
    memoization_cache[state_key] = max_full_empty_server;
    max_full_empty_server = calcu_full_empty_server();
  }

  if (recursive_count == static_cast<int>(job_list.size())) {
    return max_full_empty_server;
  }

  job_element& target_job = job_list[recursive_count];
  for (int i = 0; i < priroried_target_server.size(); ++i) {
    if (target_job.server_index == i) { continue; }

    server_entry server = server_list->at(priroried_target_server[i]);
    if (server.get_avaliable_accelator_count() < target_job.job->get_accelerator_count()) { continue; }

    if (rearrange_task(i, target_job, recursive_count, false)) {
      int full_empty_server = calcu_full_empty_server();
      if (full_empty_server > max_full_empty_server) {
        max_full_empty_server = full_empty_server;
        memoization_cache[state_key] = max_full_empty_server;
        dumpy_job_list();
      }
      max_full_empty_server = get_optimal_adjusting_dp(recursive_count + 1, max_full_empty_server, execute_count);
      rearrange_task(i, target_job, recursive_count, true);

    }
  }
  max_full_empty_server = get_optimal_adjusting_dp(recursive_count + 1, max_full_empty_server, execute_count);

  return max_full_empty_server;

}

void adjusting_server::dumpy_job_list() {
  optimal_position.clear();
  for (auto job : job_list) {
    optimal_position.push_back(job);
  }
}

int adjusting_server::calcu_full_empty_server() {
  int full_empty_server = 0;
  for (int i = 0; i < server_list->size(); ++i) {
    server_entry& server = server_list->at(i);
    if (get_empty_slot(i) == server.get_accelerator_count()) {
      full_empty_server++;
    }
  }

  return full_empty_server;
}

int adjusting_server::get_empty_slot(int server_index) {
  int i, empty_space = 0;
  if (nullptr == server_status) { return empty_space; }
  int server_pos = server_index * global_const::accelator_per_server_max;
  for (i = 0; i < global_const::accelator_per_server_max; ++i) {
    if (gpu_allocation_type::empty != server_status[server_pos + i].status) { continue; }
    empty_space++;
  }

  return empty_space;
}

void adjusting_server::switch_accelerator_status(int server_index, int count, gpu_allocation_type privious, gpu_allocation_type after) {
  if (nullptr == server_status) { return; }
  int server_pos = server_index * global_const::accelator_per_server_max;
  int i;
  for (i = 0; i < global_const::accelator_per_server_max; ++i) {
    if (0 == count) { break; }
    if (gpu_allocation_type::none == server_status[server_pos + i].status) { break; }
    if (privious == server_status[server_pos + i].status) {
      server_status[server_pos + i].status = after;
      count--;
    }
  }
}

bool adjusting_server::rearrange_task(int server_index, job_element& job_obj, int recursive_count, bool reverse) {
  int i;
  int server_pos = server_index * global_const::accelator_per_server_max;
  int required_count = job_obj.job->get_accelerator_count();

  if (nullptr == server_status) { return false; }

  if (false == reverse) {
    server_entry server = server_list->at(server_index);
    if (required_count > server.get_accelerator_count()) { return false; }

    int empty_space = get_empty_slot(server_index);
    if (empty_space < required_count) { return false; }

    switch_accelerator_status(server_index, job_obj.job->get_accelerator_count(), gpu_allocation_type::empty, gpu_allocation_type::adjusted);
    switch_accelerator_status(job_obj.server_index, job_obj.job->get_accelerator_count(), gpu_allocation_type::floating, gpu_allocation_type::empty);

    job_obj.target_index = server_index;
    return true;
  }

  switch_accelerator_status(server_index, job_obj.job->get_accelerator_count(), gpu_allocation_type::adjusted, gpu_allocation_type::empty);
  switch_accelerator_status(job_obj.server_index, job_obj.job->get_accelerator_count(), gpu_allocation_type::empty, gpu_allocation_type::floating);
  job_obj.target_index = -1;
  return true;
}

string adjusting_server::generate_state_key(int recursive_count) {
  std::ostringstream key_stream;
  key_stream << recursive_count << "-";
  for (const auto& server_idx : priroried_target_server) {
    server_entry& server = server_list->at(server_idx);
    int available_accelerators = get_empty_slot(server_idx);
    key_stream << server_idx << ":" << available_accelerators << ";";
  }
  return key_stream.str();
}