#pragma once
#include "job_entry.h"
#include "server_entry.h"
#include <vector>
#include <queue>

using namespace std;

class job_scheduler{
public:
  virtual ~job_scheduler() {};
  virtual int arrange_server(job_entry& job, int queue_index = 0, accelator_type coprocessor = accelator_type::any) = 0;
  void set_server(vector<server_entry>* server_list) { 
    target_server = server_list; 
    postproessing_set_server();
  };
  void set_scheduling_condition(bool using_preemetion, bool scheduling_follow_flavor, bool work_till_end);
  virtual int scheduling_job(int emulation_step);
  virtual void get_wait_job_request_acclerator(vector<int>& request);
  //void set_wait_queue(queue<job_entry*>* queue) { wait_queue = queue; };
  void set_wait_queue(vector<queue<job_entry*>*>* queue) { wait_queue_group = queue; };
  void set_wait_age_queue(vector<vector<job_age_struct>>* queue) { wait_queue_age = queue; };
  void set_scheduled_queue(vector<job_age_struct>* queue) { scheduled_history = queue; };
protected:
  vector<server_entry>* target_server = nullptr;
  bool preemtion_enabling = false;
  bool scheduling_with_flavor = false;
  bool perform_until_finish = false;
  string get_server_status_string();
  virtual void postproessing_set_server() = 0;
  //queue<job_entry*>* wait_queue = nullptr;
  vector<queue<job_entry*>*>* wait_queue_group = nullptr;
  vector<vector<job_age_struct>>* wait_queue_age = nullptr;
  vector<job_age_struct>* scheduled_history = nullptr;
};

