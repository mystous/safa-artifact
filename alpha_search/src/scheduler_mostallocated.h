#pragma once
#include "job_scheduler.h"
class scheduler_mostallocated :public job_scheduler {
public:
  virtual ~scheduler_mostallocated();
  virtual int arrange_server(job_entry& job, int queue_index = 0, accelator_type coprocessor = accelator_type::any) override;
  void set_strick_policy(bool strict) { strict_allocation = strict; };

protected:
  virtual void postproessing_set_server() override;

private:
  void get_suitable_server(vector<tuple<int, server_entry*>> &server, int required_accelerator);
  vector<vector<tuple<int, server_entry*>>> accelerator_count_hash_list;
  bool strict_allocation = false;
};

