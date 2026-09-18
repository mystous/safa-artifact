#pragma once
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <iomanip>
#include <chrono>
#include <limits>
#include <atomic>
#include <functional>
#include <thread>
#include <queue>
#include <cmath>
#include <numeric>

#include "job_entry.h"
#include "coprocessor_server.h"
#include "server_entry.h"
#include "job_scheduler.h"
#include "scheduler_compact.h"
#include "scheduler_fare_share.h"
#include "scheduler_mostallocated.h"
#include "scheduler_round_robin.h"
#include "scheduler_mcts.h"
#include "enum_definition.h"
#include "adjusting_server.h"
#include "global_definistion.h"

using namespace std;
using namespace std::chrono;

class job_emulator {
public:
  job_emulator();
  struct job_entry_element {
    vector<job_entry*> job_list_in_slot;
  };

  using job_entry_struct = struct job_entry_element;

  virtual ~job_emulator();


  void build_job_list(string filename, global_structure::scheduler_options options);
  void build_job_queue();
  void build_server_list(string filename);
  void set_option(global_structure::scheduler_options options);

  scheduler_type get_selction_scheduler() { return selected_scheduler; };
  bool get_preemtion_enabling() { return preemtion_enabling; };
  bool get_scheduling_with_flavor_option() { return scheduling_with_flavor; };
  bool get_finishing_condition() { return perform_until_finish; };
  bool get_prevent_starvation() { return starvation_prevention; };
  vector<job_entry>* get_job_list_ptr() { return &job_list; };
  vector<server_entry>* get_server_list() { return &server_list; };
  int get_total_time_slot() { return total_time_slot; };
  int get_progress_time_slot();
  int get_emulation_play_priod() { return emulation_play_priod; };
  void set_emulation_play_priod(int priod) { emulation_play_priod = priod; };
  string get_job_file_name() { return job_file_name; };
  void step_foward();
  void pause_progress();
  void stop_progress();
  thread::id start_progress();
  void start_progress_wo_thread();
  void exit_thread();
  void set_callback(std::function<void(void*, thread::id)> callback, void *object);
  int get_emulation_step() { return emulation_step; };
  emulation_status get_emulation_status() { return progress_status; };
  double* get_allocation_rate() { return allocation_rate; };
  double* get_utilization_rate() { return utilization_rate; };
  int get_rate_index() { return rate_index; };
  bool save_result_totaly(string file_body_name);
  bool save_result_totaly();
  bool save_waiting_time();
  bool save_waiting_time(string file_body_name);
  bool save_result_meta();
  bool save_result_meta(string file_body_name);
  bool save_result_log(string file_name);
  string get_savefile_candidate_name();
  bool save_result_log();
  string get_setting_scheduling_name() { return scheduling_name; };
  int get_total_job_count() { return job_list.size(); };
  int get_remain_job_count() { return get_total_job_count() - get_scheduled_job_count(); };
  int get_wait_job_count();// { return wait_queue.size(); };
  void get_wait_job_request_acclerator(vector<int> &request);
  int get_finished_job_count(){ return finished_job_count; };
  int get_scheduled_job_count() { return scheduled_job_count; };
  int get_done_emulation_step() { return last_emulation_step; };
  bool get_starvation_prevention_option() { return starvation_prevention; };
  chrono::duration<double> get_job_elapsed_time() { return progress_tp - job_start_tp; };
  string get_job_elapsed_time_string();
  int get_job_adjust_overhead_time() { return job_adjust_overhead_times * job_adjust_overhead_fraction; };;
  int get_job_adjust_count() { return job_adjust_overhead_times; };
  double get_age_weight_constant() { return age_weight_constant; };
  int get_dp_execution_maximum() { return dp_execution_maximum; }
  double get_starvation_prevention_criteria() { return starvation_prevention_criteria; }
  scheduler_type get_selected_scheduler() { return selected_scheduler; };
  int get_defragmentaion_criteria() { return defragmentaion_criteria; };
  void set_result_file_save_flag(bool flag) { result_file_save_flag = flag; };
  void set_max_execute_number(int number);

private:
  int job_adjust_overhead_times = 0;
  const int job_adjust_overhead_fraction = 5;
  string scheduling_name = "round_robin";
  void* call_back_object = nullptr;
  int finished_job_count = 0;
  int scheduled_job_count = 0;
  int last_scheduled_job_count = 0;
  bool result_file_save_flag = true;
  vector<job_entry> job_list;
  vector<server_entry> server_list;
  scheduler_type selected_scheduler = scheduler_type::mostallocated;
  bool preemtion_enabling = false;
  bool scheduling_with_flavor = false;
  bool perform_until_finish = false;
  bool starvation_prevention = false;
  system_clock::time_point min_start_time;
  system_clock::time_point max_end_time;
  job_entry_struct* job_queue = nullptr;
  int total_time_slot = 0;
  string job_file_name = "";
  int emulation_step = -1;
  int last_emulation_step = -1;
  int emulation_play_priod = 1;
  job_scheduler* scheduler_obj = nullptr;
  atomic<emulation_status> progress_status = emulation_status::stop;
  thread emulation_player;
  vector<queue<job_entry*>*> wait_queue_group;
  vector<vector<job_age_struct>> wait_queue_age;
  vector<job_age_struct> scheduled_history;
  const int sleep_for_drawing = 1;
  double* allocation_rate = nullptr;
  double* utilization_rate = nullptr;
  double latest_allocation = 0.0;
  int rate_index = 0;
  vector<double*> server_utilization_rate;
  vector<int*> server_allocation_count;
  const string compact_scheduler_name = "compact";
  const string fare_share_scheduler_name = "fare_share";
  const string mostallocated_scheduler_name = "mostallocated";
  const string mcts_scheduler_name = "mcts";
  const string round_robin_scheduler_name = "round_robin";
  bool saving_possiblity = false;
  int memory_alloc_size = 0;
  system_clock::time_point job_start_tp;
  system_clock::time_point progress_tp;
  int max_age_count = 0;
  int max_age_count_constant = global_const::queue_prefix_mult;   // 민감도 스윕: prefix 배수
  double r_penalty_constant = global_const::r_penalty;            // 민감도 스윕: R 감쇠
  double priority_base_constant = global_const::priority_base;    // 민감도 스윕: P 밑
  double starvation_prevention_criteria = global_const::starvation_upper;
  double age_weight_constant = global_const::age_weight;
  int dp_execution_maximum = global_const::dp_execution_maximum;
  vector<int> preemption_object;
  int defragmentaion_criteria = global_const::defragmentation_criteria;
  function<void(void*, thread::id)> step_forward_callback;
  bool do_defragmentation = false;
  double allocation_stats[global_const::statistics_array_size];
  double utilization_stats[global_const::statistics_array_size];

  void update_wait_queue();
  void adjust_wait_queue();
  //void scheduling_job();
  void computing_forward();
  void initialize_server_state();
  void initialize_job_state();
  void initialize_wait_queue();
  void delete_rate_array();
  void delete_wait_queue();
  void log_rate_info();
  void delete_server_info_log();
  bool check_finishing();
  void initialize_progress_variables();
  void reallocation_log_memory();
  void defragmentation_excute(bool &do_defragmentation);
  void check_defragmentation_condition(bool& do_defragmentation);
  void calculate_statistics(double* rate_array, int size, double* stats);
  adjusting_server* server_control = nullptr;
};

