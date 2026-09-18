#include "pch.h"
#include "scheduler_round_robin.h"

int scheduler_round_robin::arrange_server(job_entry& job, int queue_index, accelator_type coprocessor) {
  int arrange_server = -1, i;

  for (i = 0; i < target_server->size(); ++i) {
    server_entry *target = &target_server->at(current_server_index);

    if (scheduling_with_flavor) {
      if (coprocessor != target->get_accelator_type()) {
        current_server_index = get_next_server_index();
        continue;
      }
    }

    if (target->get_avaliable_accelator_count() < job.get_accelerator_count()) {
      current_server_index = get_next_server_index();
      continue;
    }
    target->assign_accelator(&job, job.get_accelerator_count());
    arrange_server = current_server_index;
    get_next_server_index();
    break;
  }
  
  return arrange_server;
}

int scheduler_round_robin::get_next_server_index() {
  current_server_index++;

  if (current_server_index == target_server->size()) {
    current_server_index = 0;
  }

  return current_server_index;
}

void scheduler_round_robin::postproessing_set_server(){
  
}