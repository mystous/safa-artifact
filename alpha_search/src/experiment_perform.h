#pragma once
#include "job_emulator.h"
#include <vector>
#include <thread>
#include <iostream>
#include <atomic>
#include <unordered_map>

using namespace std;

class experiment_perform
{
public:
  virtual ~experiment_perform();
  void set_hyperparameter(vector<global_structure::scheduler_options>* func) { hyperparameter = func; };
  bool set_thread_count(int thread_num);
  void set_call_back(function<void(void*, thread::id)> callback) { callback_func = callback; };
  void set_message_call_back(function<void(void*, string)> callback) { message_callback_func = callback;  };
  void set_call_back_obj(void* ptr) { object = ptr; };
  void set_file_name(string task_file, string server_file);
  vector<string> start_experiment(bool using_thread = true);
  bool call_back_from_thread(thread::id id, string &complate, string &start);
  int get_complated_experiment() { return complated_experiment; };
  void stop_experiment();
  string get_result_dir() { return result_dir; };
private:
  struct thread_data {
    thread::id              id;
    job_emulator*           emulator = nullptr;
    int                     option_index = 0;
    int                     handling_opt_count = 0;
    int                     experiment_done = 0;
    int                     start_index = -1;
    system_clock::time_point job_start_tp;
  };

  using thread_meta = struct thread_data;
  vector<job_emulator*> emulator_vector;
  vector<global_structure::scheduler_options>* hyperparameter = nullptr;
  int num_per_thread;
  int last_one_standing;
  int thread_count;
  string task_file_name;
  string server_file_name;
  int complated_experiment;
  string get_progress();

  function<void(void*, thread::id)> callback_func;
  function<void(void*, string)> message_callback_func;
  void* object = nullptr;
  unordered_map<thread::id, thread_meta*> thread_map;
  vector<thread_meta*> thread_meta_list;
  void start_emulator_with_meta(thread_meta* meta, bool first_call = true);
  string result_dir;

  void initialize_emul_vector();
  void initialize_thread_map();
  string build_new_thread_start_string(thread_meta* meta);
};

