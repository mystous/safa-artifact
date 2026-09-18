#include "pch.h"
#include "scheduler_mostallocated.h"
#include <algorithm>

using namespace std;

scheduler_mostallocated::~scheduler_mostallocated() {
  //accelerator_count_hash_list.clear();
}

int scheduler_mostallocated::arrange_server(job_entry& job, int queue_index, accelator_type coprocessor) {
  const int max_value = 999999;
  int arrange_server = -1, i;
  int min_gap = max_value;
  vector<tuple<int, int, int>> candidate;
  vector<tuple<int, server_entry*>> suitable_server_list;

  get_suitable_server(suitable_server_list, job.get_accelerator_count());
  for (auto& [index, server] : suitable_server_list) {

    if (scheduling_with_flavor) {
      if (coprocessor != server->get_accelator_type()) { continue; }
    }

    if (server->get_avaliable_accelator_count() < job.get_accelerator_count()) { continue; }

    int gap = server->get_avaliable_accelator_count() - job.get_accelerator_count();
    candidate.emplace_back(index, server->get_avaliable_accelator_count(), gap);

    if (gap < min_gap) {
      min_gap = gap;
    }
  }

  for (auto& [index, server_accelator_count, gap] : candidate) {
    if (min_gap != gap) { continue; }
    arrange_server = index;
    break;
  }

  if (-1 != arrange_server) {
    server_entry* target = &target_server->at(arrange_server);
    target->assign_accelator(&job, job.get_accelerator_count());
    return arrange_server;
  }

  if (strict_allocation) {
    return arrange_server;
  }

  for (i = 0; i < target_server->size(); ++i) {
    server_entry* target = &target_server->at(i);
    if (target->get_avaliable_accelator_count() < job.get_accelerator_count()) { continue; }
    arrange_server = i;
    break;
  }
    
  if (-1 != arrange_server) {
    server_entry* target = &target_server->at(arrange_server);
    target->assign_accelator(&job, job.get_accelerator_count());
  }
  return arrange_server;
}

void scheduler_mostallocated::get_suitable_server(vector<tuple<int, server_entry*>>& server, int required_accelerator){
  int max_accelrator_count = accelerator_count_hash_list.size();
  if (required_accelerator > max_accelrator_count - 1) { return; }

  for (int i = required_accelerator; i <= max_accelrator_count; ++i) {
    if (accelerator_count_hash_list[i].size() > 0) {
      server = accelerator_count_hash_list[i];
      break;
    }
  }
}

void scheduler_mostallocated::postproessing_set_server() {
  int max_accelerator_count = 0;
  for (int i = 0; i < target_server->size(); i++) {
    server_entry* server = &target_server->at(i);
    int accelerator_count = server->get_accelerator_count();
    max_accelerator_count = std::max(max_accelerator_count, accelerator_count);
  }

  for (auto&& list : accelerator_count_hash_list) {
    list.clear();
  }
  accelerator_count_hash_list.clear();
  accelerator_count_hash_list.resize(max_accelerator_count + 1);

  for (int i = 0; i < target_server->size(); i++) {
    server_entry* server = &target_server->at(i);
    int accelerator_count = server->get_accelerator_count();
    accelerator_count_hash_list[accelerator_count].emplace_back(i, server);
  }
}