#pragma once
#include <unordered_map>
#include <vector>
#include <functional>
#include <set>
#include <queue>
#include <unordered_map>
#include "server_entry.h"

namespace std {
  template<typename T1, typename T2>
  struct hash<std::pair<T1, T2>> {
    std::size_t operator()(const std::pair<T1, T2>& p) const {
      std::size_t h1 = std::hash<T1>()(p.first);
      std::size_t h2 = std::hash<T2>()(p.second);
      return h1 ^ (h2 << 1); // 두 해시 값을 결합
    }
  };
}


class adjusting_server
{
public:
  adjusting_server(vector<server_entry>* servers, int execute_maximum)
    : server_list(servers), max_execute_number(execute_maximum){};
  virtual ~adjusting_server();

  bool defragementation(int step);
  void set_max_execute_number(int number) { max_execute_number = number; };
private:
  struct server_status_for_dp {
    gpu_allocation_type     status;
    string                  job_id;
  };
  struct job_for_dp {
    job_for_dp(job_entry* job_instance, int server_number/*, int accelerator_pos*/) :
      job{ job_instance }, server_index{ server_number }/*, accelerator_index{accelerator_pos}*/ {};
    job_entry* job = nullptr;
    int                     server_index = -1;
    int                     target_index = -1;
    //int                     accelerator_index = -1;
  };
  using server_map = struct server_status_for_dp;
  using job_element = struct job_for_dp;

  vector<server_entry>* server_list = nullptr;
  gpu_defragmentation_method adjusting_method = gpu_defragmentation_method::max_space;
  server_map* server_status = nullptr;
  vector<job_element> job_list;
  vector<job_element> optimal_position;
  unordered_multimap<int, job_entry*> target_job;
  set<int> target_server;
  vector<int> priroried_target_server;
  unordered_map<string, int> memoization_cache;
  vector<int>* target_accelerator_count;
  int max_execute_number = 1000000;


  void reconstruct_server_status();
  bool compare_server_priority(int op1, int op2);
  job_entry* get_job_entry(string job_id, vector<job_entry*> job_list);
  int get_optimal_adjusting_dp(int recursive_count, int & max_full_empty_server, int &execute_count);
  bool rearrange_task(int server_index, job_element& job_obj, int recursive_count, bool reverse);
  int calcu_full_empty_server();
  void dumpy_job_list();
  void build_dp_target();
  int get_empty_slot(int server_index);
  void switch_accelerator_status(int server_index, int count, gpu_allocation_type privious, gpu_allocation_type after);
  void adjust_job_allocation();
  string generate_state_key(int recursive_count);
};

