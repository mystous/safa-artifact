#pragma once
#include <string>
#include <fstream>
#include <vector>
#include <cstdlib>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <chrono>
#include <random>
#include "enum_definition.h"

using namespace std;
using namespace std::chrono;

class log_generator
{
public:
  struct task_entiry_meta{
    string pod_name;
    string pod_type;
    string project;
    string namespace_;  
    string user_team;
    string start;
    system_clock::time_point start_tp;
    string finish;
    system_clock::time_point finish_tp;
    int count;
    string time_diff;
    duration<double, ratio<60>> time_diff_tp;
    int computing_load;
    double gpu_utilization;
    string flavor;
    string preemption;
  };

  struct distribution_values_meta {
    int array_size = -1;
    system_clock::time_point* start_tp = nullptr;
    system_clock::time_point* finish_tp = nullptr;
    int* counts = nullptr;
    float* utilizations = nullptr;
    bool* preemptions = nullptr;
    accelator_type* accelerators = nullptr;
  };
  using task_entity = struct task_entiry_meta;
  using distribution_values = struct distribution_values_meta;
  log_generator();
  log_generator(int task_size);
  log_generator(int task_size, distribution_type gpu_count_dist, distribution_type wall_time_dist,
    distribution_type computation_dist, distribution_type flaver_dist, distribution_type preemetion_dist);
  virtual ~log_generator();
  string get_savefile_candidate_name();
  bool save_log(string filename);
  bool get_generation_sucessed_result() { return generation_sucessed; };

private:
  static string generate_random_string(int length);
  static string generate_random_timestamp();
  void generate_seed_tp();
  bool start_generation();
  void set_whole_walltime(int day_count);
  bool generate_random_task(task_entity& task);
  bool generate_distribution_task(task_entity& task, distribution_values& dist, int index);
  bool generate_distribution_tasks();
  bool generate_task(task_entity& task, distribution_values* data, int index = random_gen_index);
  void generate_task_postproecess(task_entity& task);
  int task_count = 1000;
  task_entity* gen_data = nullptr;
  system_clock::time_point seed_tp;
  void finialize_pointer();
  void generate_time_point_distribution(system_clock::time_point* tp, 
                                        distribution_type distribution_method,
                                        system_clock::time_point* start_tp, 
                                        duration<double, ratio<60>>range, 
                                        int task_size);
  template<typename distribution>
  void generate_time_point_distribution_inner(system_clock::time_point* tp,
                                              system_clock::time_point* start_tp, 
                                              distribution_type distribution_method,
                                              distribution& dist,
                                              int task_size);
  template<typename datatype>
  void generate_array_distribution(datatype* array, 
                                  datatype* seed, 
                                  distribution_type distribution_method,
                                  datatype range,
                                  int task_size, 
                                  datatype min_value, 
                                  datatype max_value);

  template<typename T, typename distribution_data>
  void generate_array_distribution_inner(T* array,
                                        T* seed,
                                        distribution_data& dist,
                                        int task_size,
                                        T min_value,
                                        T max_value);

  template<typename TT, typename distribution_value>
  void generate_discrete_distribution_inner(TT* array, TT* seed, distribution_value& dist, int seed_size, int task_size);

  template<typename datatype>
  void generate_discrete_distribution(datatype* array, datatype* seed, distribution_type distribution_method, int seed_size, int task_size);

  void generate_distribution(distribution_values& dist, int task_size);
  void finialize_distribution(distribution_values& dist);
  bool generate_random_tasks();
  bool initialize_distribution(distribution_values& dist, int task_size);

  bool initialize_pointer(int task_size);
  bool random_generation = true;
  distribution_type gpu_count_distribution;
  distribution_type wall_time_distribution; 
  distribution_type computation_distribution; 
  distribution_type flaver_distribution; 
  distribution_type preemetion_diststribution;
  bool start_from_now = true;
  int gen_time_duration_tp = 180;
  const static int random_gen_index = -1;
  const static int multi_const = 200;
  double chi_dof = 10.0;
  bool generation_sucessed = false;
  int max_task_running = 3600;
  random_device rd;
};

