#pragma once
#include "job_scheduler.h"
class scheduler_round_robin : public job_scheduler{
public:
  virtual ~scheduler_round_robin() {};
  virtual int arrange_server(job_entry& job, int queue_index = 0, accelator_type coprocessor = accelator_type::any) override;
private:
  int current_server_index = 0;
  int get_next_server_index();
  virtual void postproessing_set_server() override;
};

