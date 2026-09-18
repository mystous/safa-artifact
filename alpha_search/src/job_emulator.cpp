#include "pch.h"
#include "job_emulator.h"
#include <ctime>
#include "utility_class.h"
#include <mutex>


#ifdef _WIN32
#include <Windows.h>
#include <mmsystem.h>
#pragma comment(lib, "winmm.lib")
#else
#include <unistd.h>
#include <cstring>
#endif

using namespace std;
using namespace std::chrono;

template <typename T>
T* reallocate(T* oldArray, size_t oldSize, size_t newSize) {
  T* newArray = new T[newSize];
  std::memcpy(newArray, oldArray, oldSize * sizeof(T));
  delete[] oldArray;
  return newArray;
}

job_emulator::job_emulator() {

}

void job_emulator::initialize_wait_queue() {
  for (int i = 0; i < global_const::accelator_category_count + 1; ++i) {
    queue<job_entry*>* new_element = new queue<job_entry*>();
    wait_queue_group.push_back(new_element);
    vector<job_age_struct> new_age_queue;
    wait_queue_age.push_back(new_age_queue);
  }
}

job_emulator::~job_emulator() {
  if (nullptr != job_queue) {
    delete[] job_queue;
  }

  if (nullptr != scheduler_obj) {
    delete scheduler_obj;
  }

  if (nullptr != server_control) {
    delete server_control;
  }

  delete_wait_queue();
  delete_rate_array();
  delete_server_info_log();
}

void job_emulator::initialize_job_state() {
  for (auto&& job : job_list) {
    job.reset();
  }
}

void job_emulator::initialize_server_state() {
  for (auto&& server : server_list) {
    server.build_accelator_status();
  }
}

void job_emulator::delete_server_info_log() {
  for (int i = 0; i < server_utilization_rate.size(); ++i) {
    double* server_utilization = server_utilization_rate[i];
    if (nullptr != server_utilization) {
      delete server_utilization;
      server_utilization = nullptr;
    }

    int* server_allocation = server_allocation_count[i];
    if (nullptr != server_allocation) {
      delete server_allocation;
      server_allocation = nullptr;
    }
  }

  
  server_utilization_rate.clear();
  server_allocation_count.clear();
}

void job_emulator::delete_wait_queue() {
  for (auto && queue : wait_queue_group) {
    if (nullptr != queue) {
      delete queue;
      queue = nullptr;
    }
  }
  wait_queue_group.clear();
}

void job_emulator::build_server_list(string filename) {
  ifstream file(filename);

  if (!file.is_open()) {
    cerr << "File cannot be opened.\n";
    return;
  }
  delete_server_info_log();
  server_list.clear();

  string line;
  while (getline(file, line)) {
    istringstream ss(line);
    string token;
    vector<string> tokens;

    while (std::getline(ss, token, ',')) {
      tokens.push_back(token);
    }

    int accelerator_count = stoi(tokens[1]);
    server_entry new_element(tokens[0], server_entry::get_accelerator_type(tokens[2]), accelerator_count);
    server_list.push_back(new_element);
    max_age_count = server_list.size() * max_age_count_constant;
  }

  scheduler_obj->set_server(&server_list);
  if (nullptr == server_control) {
    server_control = new adjusting_server(&server_list, dp_execution_maximum);
  }
  //server_control->reconstruct_server_status();
  
  file.close();
}

void job_emulator::set_max_execute_number(int number) {
  if (nullptr == server_control) { return; }

  server_control->set_max_execute_number(number);
}

void job_emulator::build_job_list(string filename, global_structure::scheduler_options options) {
  ifstream file(filename);

  if (!file.is_open()) {
    cerr << "File cannot be opened.\n";
    return;
  }

  job_file_name = filename;
  set_option(options);
  job_list.clear();

  string line;
  while (getline(file, line)) {
    istringstream ss(line);
    string token;
    vector<string> tokens;

    while (std::getline(ss, token, ',')) {
      tokens.push_back(token);
    }

    if (tokens[0] == "pod_name" && tokens[1] == "pod_type") { continue; }

    int computation_level = 1;
    double gpu_utilization = 50.;
    bool preemption_enable = false;
    accelator_type accelator = accelator_type::cpu;

    if (tokens.size() > 9) {
      computation_level = stoi(tokens[9]);
      gpu_utilization = stod(tokens[10]);
    }


    if (tokens.size() > 11) {
      accelator = server_entry::get_accelerator_type(tokens[11]);
    }

    if (tokens.size() > 12) {
      preemption_enable = tokens[12] == "y" ? true : false;
    }

    job_entry new_element(tokens[0], tokens[1], tokens[2], tokens[3], 
                          tokens[4], tokens[5], tokens[6], stoi(tokens[7]), 
                          computation_level, gpu_utilization, accelator, preemption_enable);
    job_list.push_back(new_element);
  }

  file.close();
}

void job_emulator::set_callback(std::function<void(void*, thread::id)> callback, void* object) {
  step_forward_callback = callback; 
  call_back_object = object;
};

string job_emulator::get_job_elapsed_time_string() {
  auto elapsed = get_job_elapsed_time();

  auto hours = chrono::duration_cast<chrono::hours>(elapsed);
  elapsed -= hours;
  auto minutes = chrono::duration_cast<chrono::minutes>(elapsed);
  elapsed -= minutes;
  auto seconds = chrono::duration_cast<chrono::seconds>(elapsed);
  elapsed -= seconds;
  auto milliseconds = chrono::duration_cast<chrono::milliseconds>(elapsed);

  ostringstream oss;
  oss << setw(2) << setfill('0') << hours.count() << ":"
    << setw(2) << setfill('0') << minutes.count() << ":"
    << setw(2) << setfill('0') << seconds.count() << ":"
    << std::setw(3) << std::setfill('0') << milliseconds.count();
  string rtn = oss.str();
  return rtn;
}

void job_emulator::build_job_queue() {
  if (job_list.size() < 1) {
    return;
  }

  min_start_time = job_list[0].get_start_tp();
  max_end_time = job_list[0].get_finish_tp();

  for (const auto& job : job_list) {
    if (job.get_start_tp() < min_start_time) {
      min_start_time = job.get_start_tp();
    }
    if (job.get_finish_tp() > max_end_time) {
      max_end_time = job.get_finish_tp();
    }
  }

  auto diff = duration_cast<minutes>(max_end_time - min_start_time);
  total_time_slot = diff.count();
  job_queue = new job_entry_struct[total_time_slot];

  for (int i = 0; i < job_list.size(); ++i) {
    job_entry* job = &job_list[i];
    auto startDiff = duration_cast<std::chrono::minutes>(job->get_start_tp() - min_start_time);
    job_queue[startDiff.count()].job_list_in_slot.push_back(job);
  }
}

void job_emulator::get_wait_job_request_acclerator(vector<int>& request) {
  scheduler_obj->get_wait_job_request_acclerator(request);
}

void job_emulator::set_option(global_structure::scheduler_options options) {
  preemtion_enabling = options.using_preemetion;
  scheduling_with_flavor = options.scheduleing_with_flavor_option;
  selected_scheduler = options.scheduler_index;
  perform_until_finish = options.working_till_end;
  starvation_prevention = options.prevent_starvation;
  starvation_prevention_criteria = options.svp_upper;
  age_weight_constant = options.age_weight;
  dp_execution_maximum = options.reorder_count;
  defragmentaion_criteria = options.preemption_task_window;
  r_penalty_constant = options.r_penalty;
  priority_base_constant = options.priority_base;
  max_age_count_constant = options.queue_prefix_mult;
  max_age_count = server_list.size() * max_age_count_constant;  // 서버 로드 후 set_option 호출 대비
  if (nullptr != scheduler_obj) {
    delete scheduler_obj;
  }

  switch (selected_scheduler) {
  case scheduler_type::compact:
    scheduler_obj = new scheduler_compact();
    scheduling_name = compact_scheduler_name;
    break;
  case scheduler_type::fare_share:
    scheduler_obj = new scheduler_fare_share();
    scheduling_name = fare_share_scheduler_name;
    break;
  case scheduler_type::mostallocated: 
    scheduler_obj = new scheduler_mostallocated();
    scheduling_name = mostallocated_scheduler_name;
    break;
  case scheduler_type::mcts:
    scheduler_obj = new scheduler_mcts();
    scheduling_name = mcts_scheduler_name;
    break;
  case scheduler_type::round_robin:
  default:
    scheduler_obj = new scheduler_round_robin();
    scheduling_name = round_robin_scheduler_name;
    break;
  }
  scheduler_obj->set_wait_queue(&wait_queue_group);
  scheduler_obj->set_wait_age_queue(&wait_queue_age);
  scheduler_obj->set_scheduled_queue(&scheduled_history);
  scheduler_obj->set_server(&server_list);
  scheduler_obj->set_scheduling_condition(preemtion_enabling, scheduling_with_flavor, perform_until_finish);
}

void job_emulator::step_foward() {
  if (check_finishing()) {
    last_emulation_step = emulation_step;
    emulation_step = -1;
    progress_status = emulation_status::stop;
    initialize_server_state();
    initialize_job_state();
    calculate_statistics(allocation_rate, rate_index-1, allocation_stats);
    calculate_statistics(utilization_rate, rate_index-1, utilization_stats);
    return;
  }

  emulation_step++;
  computing_forward();
  update_wait_queue();
  adjust_wait_queue();
  defragmentation_excute(do_defragmentation);
  scheduled_job_count += scheduler_obj->scheduling_job(emulation_step);
  check_defragmentation_condition(do_defragmentation);
  log_rate_info();
  step_forward_callback(call_back_object, this_thread::get_id());

  progress_tp = system_clock::now();
}

void job_emulator::defragmentation_excute(bool& do_defragmentation) {
  if (!preemtion_enabling) { return; }
  if (defragmentaion_criteria < [=]()->int {
    int wait_job_count = 0;

    for (auto&& queue : wait_queue_group) {
      wait_job_count += queue->size();
    }
    return wait_job_count;
    }() && true == do_defragmentation) {

    if (server_control->defragementation(emulation_step)) {
      job_adjust_overhead_times++;
    }
    do_defragmentation = false;
  }
}

void job_emulator::check_defragmentation_condition(bool& do_defragmentation) {
  if (!preemtion_enabling) { return; }

  if (last_scheduled_job_count != scheduled_job_count) {
    last_scheduled_job_count = scheduled_job_count;
    do_defragmentation = true;
  }
  else {
    do_defragmentation = false;
  }
}

bool job_emulator::check_finishing() {
  bool finished_condition = false;
  if (perform_until_finish) {
    if (get_total_job_count() == get_scheduled_job_count()) {
      int server_size = server_list.size();
      finished_condition = true;
      for (int i = 0; i < server_size; ++i) {
        server_entry server = server_list.at(i);
        if (server.get_loaded_job_count() > 0) {
          finished_condition = false;
          break;
        }
      }
    }
    return finished_condition;
  }
  
  if ((total_time_slot - 1) == emulation_step) {
    finished_condition = true;
  }

  return finished_condition;
}


void job_emulator::log_rate_info() {
  if (rate_index >= memory_alloc_size) {
    reallocation_log_memory();
  }
  int total_reserved_count = 0, total_GPU_count = 0;
  double reserved_utilization = 0.0;
  int server_size = server_list.size();

  for (int i = 0; i < server_size; ++i) {
    server_entry server = server_list.at(i);

    int accelerator_count = server.get_accelerator_count();
    int avaliable_accelerator_count = server.get_avaliable_accelator_count();
    double utilization_rate = server.get_server_utilization();
    total_GPU_count += accelerator_count;
    total_reserved_count += (accelerator_count - avaliable_accelerator_count);
    reserved_utilization += utilization_rate;

    server_utilization_rate[i][rate_index] = utilization_rate;
    server_allocation_count[i][rate_index] = accelerator_count - avaliable_accelerator_count;
  }

  allocation_rate[rate_index] = (double)total_reserved_count / (double)total_GPU_count * 100;
  latest_allocation = allocation_rate[rate_index];
  utilization_rate[rate_index] = reserved_utilization / (double)server_size;
  rate_index++;
}

void job_emulator::computing_forward() {
  for (auto&& server : server_list) {
    server.ticktok();
    finished_job_count += server.flush();
  }
}

void job_emulator::adjust_wait_queue() {
  if (!starvation_prevention) { return; }
  if (latest_allocation > starvation_prevention_criteria) { return; }
  const int accelerator_count = 8;
  double resource_suitability_index[accelerator_count] = {0,};

  for (auto&& server : server_list) {
    int avaliable_accelator_count = server.get_avaliable_accelator_count();
    for (int i = 0; i < accelerator_count; ++i) {
      if ((avaliable_accelator_count - i) <= 0) { continue; }
      double suitablitiy_index = 1 - (avaliable_accelator_count - i - 1) * r_penalty_constant;
      if (suitablitiy_index > resource_suitability_index[i]) {
        resource_suitability_index[i] = suitablitiy_index;
      }
    }
  }

  for( int i = 0 ; i < wait_queue_age.size() ; ++i){
    auto wait_queue = wait_queue_age[i];
    int max_repriority_score_index = 0;
    double max_repriority_score = 0.;
    for (int j = 0; j < wait_queue.size(); ++j) {
      double priority = 1 * ( 1 / pow(priority_base_constant, j));
      double starvation_score = wait_queue[j].age 
                                * age_weight_constant 
                                * resource_suitability_index[wait_queue[j].job->get_accelerator_count()-1];
      wait_queue[j].repriority_score = priority + starvation_score;
      if (wait_queue[j].repriority_score > max_repriority_score) {
        max_repriority_score = wait_queue[j].repriority_score;
        max_repriority_score_index = j;
      }
    }

    if (0 != max_repriority_score_index) {
      job_age job_high_prioirty = wait_queue[max_repriority_score_index];
      wait_queue.erase(wait_queue.begin() + max_repriority_score_index);
      wait_queue.insert(wait_queue.begin(), job_high_prioirty);

      queue<job_entry*> shadow_queue = *wait_queue_group[i];
      job_entry* adjust_top_priorty = nullptr;
      queue<job_entry*> temp_queue;

      int repeat_count = shadow_queue.size();
      for (int j = 0; j < repeat_count; ++j) {
        job_entry* job = shadow_queue.front();
        if (max_repriority_score_index == j) {
          adjust_top_priorty = job;
        }
        shadow_queue.pop();
      }

      shadow_queue = *wait_queue_group[i];
      temp_queue.push(adjust_top_priorty);
      repeat_count = shadow_queue.size();
      for (int j = 0; j < repeat_count; ++j) {
        job_entry* job = shadow_queue.front();
        if (max_repriority_score_index != j) {
          temp_queue.push(job);
        }
        shadow_queue.pop();
      }

      wait_queue_age[i] = wait_queue;
      *wait_queue_group[i] = temp_queue;
    }

    if (false == scheduling_with_flavor) { break; }
  }
}

void job_emulator::update_wait_queue() {

  if (emulation_step >= get_total_time_slot()) { return; }

  if (job_queue[emulation_step].job_list_in_slot.size() > 0) {
    for (auto&& job : job_queue[emulation_step].job_list_in_slot) {
      int queue_index = 0;
      if (scheduling_with_flavor) {
        queue_index = static_cast<int>(job->get_flavor());
      }
      wait_queue_group[queue_index]->push(job);
      queue<job_entry*> shadow_queue = *wait_queue_group[queue_index];
      int copy_size = shadow_queue.size() > max_age_count ? max_age_count : shadow_queue.size();
      wait_queue_age[queue_index].clear();
      for (int i = 0; i < copy_size; ++i) {
        wait_queue_age[queue_index].push_back(job_age_struct(shadow_queue.front()));
        shadow_queue.pop();
      }
    }
  }
}

void job_emulator::pause_progress() {
  progress_status = emulation_status::pause;
  last_emulation_step = emulation_step;

#ifdef _WIN32
  TRACE(_T("\nPause progress\n"));
#else
  printf("\nPause progress\n");
#endif
}

void job_emulator::stop_progress() {
  if (emulation_status::pause == progress_status) {
    last_emulation_step = emulation_step;
    emulation_step = -1;
  }
  progress_status = emulation_status::stop;
  initialize_server_state();
  initialize_job_state();

#ifdef _WIN32
  TRACE(_T("\nStop progress\n"));
#else
  printf("\nStop progress\n");
#endif
}

void job_emulator::exit_thread() {
  if (emulation_player.joinable()) {
    emulation_player.join();
  }
}

void job_emulator::delete_rate_array() {
  if (nullptr != allocation_rate) {
    delete allocation_rate;
    allocation_rate = nullptr;
  }
  if (nullptr != utilization_rate) {
    delete utilization_rate;
    utilization_rate = nullptr;
  }
}

void job_emulator::reallocation_log_memory() {
  int old_memory_size = memory_alloc_size;
  memory_alloc_size *= 2;
  allocation_rate = reallocate(allocation_rate, old_memory_size, memory_alloc_size);
  utilization_rate = reallocate(utilization_rate, old_memory_size, memory_alloc_size);
  int server_count = server_list.size();

  for (int i = 0; i < server_list.size(); ++i) {
    server_entry server = server_list.at(i);

    server_utilization_rate[i] = reallocate(server_utilization_rate[i], old_memory_size, memory_alloc_size);
    server_allocation_count[i] = reallocate(server_allocation_count[i], old_memory_size, memory_alloc_size);
  }
}

void job_emulator::initialize_progress_variables() {
  rate_index = 0;
  finished_job_count = 0;
  scheduled_job_count = 0;
  last_scheduled_job_count = 0;
  memory_alloc_size = get_total_time_slot();
  job_adjust_overhead_times = 0;
  do_defragmentation = false;
  fill(allocation_stats, allocation_stats + (global_const::statistics_array_size-1), 0.0);
  fill(utilization_stats, utilization_stats + (global_const::statistics_array_size-1), 0.0);

  scheduled_history.clear();

  allocation_rate = new double[memory_alloc_size];
  utilization_rate = new double[memory_alloc_size];

  int server_count = server_list.size();

  for (int i = 0; i < server_count; ++i) {
    double* utilization = new double[memory_alloc_size];
    memset(utilization, 0.0, sizeof(double) * memory_alloc_size);
    server_utilization_rate.push_back(utilization);

    int* allocation = new int[memory_alloc_size];
    memset(allocation, 0, sizeof(int) * memory_alloc_size);
    server_allocation_count.push_back(allocation);
  }
}

int job_emulator::get_wait_job_count() {
  int wait_job_count = 0;

  for (auto&& queue : wait_queue_group) {
    wait_job_count += queue->size();
  }
  return wait_job_count;
}

thread::id job_emulator::start_progress() {
  set_emulation_play_priod(0.1);

  delete_rate_array();
  delete_server_info_log();
  delete_wait_queue();
  initialize_progress_variables();
  initialize_wait_queue();

  if (emulation_status::pause != this->progress_status) {
    job_start_tp = system_clock::now();
  }
  
  emulation_player = thread([this]() {
    this->progress_status = emulation_status::start;
    job_emulator* object = this;

    while (emulation_status::start == this->progress_status) {
      saving_possiblity = true;
      this->step_foward();
      auto next_call = steady_clock::now() + milliseconds(this->get_emulation_play_priod());
      this_thread::sleep_until(next_call);
    }
    if (progress_status == emulation_status::stop) {
      emulation_step = -1;
    }
    step_forward_callback(call_back_object, this_thread::get_id());
    });
  thread::id id = emulation_player.get_id();
  emulation_player.detach();
  return id;
}

void job_emulator::start_progress_wo_thread() {
  set_emulation_play_priod(0.1);

  delete_rate_array();
  delete_server_info_log();
  delete_wait_queue();
  initialize_progress_variables();
  initialize_wait_queue();

  if (emulation_status::pause != progress_status) {
    job_start_tp = system_clock::now();
  }

  progress_status = emulation_status::start;
  job_emulator* object = this;

  while (emulation_status::start == progress_status) {
    saving_possiblity = true;
    step_foward();
  }

  if (progress_status == emulation_status::stop) {
    emulation_step = -1;
  }
}

bool job_emulator::save_result_totaly() {
  return save_result_totaly(get_savefile_candidate_name());
}

bool job_emulator::save_result_totaly(string file_body_name) {
  bool rtn_result = true;
  const int result_size = 3;
  bool result[result_size] = {false,};
  
  result[1] = save_result_meta(file_body_name);
  result[2] = save_waiting_time(file_body_name);
  result[0] = true;
  if (result_file_save_flag) {
    result[0] = save_result_log(file_body_name);
  }

  for (int i = 0; i < result_size; ++i) {
    rtn_result &= result[i];
  }

  return rtn_result;
}

bool job_emulator::save_waiting_time() {
  return save_waiting_time(get_savefile_candidate_name());
}
bool job_emulator::save_waiting_time(string file_body_name) {
  ofstream file(file_body_name + ".tasklog");
  int index = 0;
  string message;
  if (!saving_possiblity) { return false; }
  if (!file.is_open()) { return false; }

  file << "Index,job id,Accumulated Age,Start Step,Following Gap,Required Accelerator Count,Utilization,Preemption,Flaver Index,Flaver,User Tem,Pod Name,Name Space,Project";
  string result = ",";
  for (size_t i = 0; i < server_list.size(); ++i) {
    server_entry server = server_list.at(i);
    string server_name = server.get_server_name();

    result += "server_name, " + server_name + "_accelerator_count, " + server_name + "_reserved_count";

    if (i != server_list.size() - 1) {
      result += ", ";
    }
  }
  int last_emulation_step = scheduled_history[0].emulation_step;
  file << result << "\n";
  for (auto&& job_meta : scheduled_history) {
    file << index++ << ","
      << job_meta.job->get_job_id() << ","
      << job_meta.accumulated_age << ","
      << job_meta.emulation_step << ","
      << job_meta.emulation_step - last_emulation_step << ","
      << job_meta.job->get_accelerator_count() << ","
      << job_meta.job->get_utilization() << ",";
    last_emulation_step = job_meta.emulation_step;
    message = job_meta.job->is_preemtion_possible() ? "true" : "false";
    file << message << ","
      << static_cast<int>(job_meta.job->get_flavor()) << ","
      << utility_class::get_accelerator_name(job_meta.job->get_flavor()) << ","
      << job_meta.job->get_user_team() << ","
      << job_meta.job->get_pod_name() << ","
      << job_meta.job->get_name_sapce() << ","
      << job_meta.job->get_project_name() << ","
      << job_meta.server_status << "\n";
  }

  file.close();
  return true;
}

bool job_emulator::save_result_meta() {
  return save_result_meta(get_savefile_candidate_name());
}

bool job_emulator::save_result_meta(string file_body_name)
{
  ofstream file(file_body_name + ".meta");

  if (!saving_possiblity) { return false; }
  if (!file.is_open()) { return false; }
  string message;
  double value;
  int value_;

  file << "Item,Contents" << "\n";
  file << "start time," << utility_class::conver_tp_str(job_start_tp) << "\n";
  file << "scheduler index," << static_cast<int>(selected_scheduler) << "\n";
  file << "scheduler name," << get_setting_scheduling_name() << "\n";
  value_ = static_cast<int>(get_job_list_ptr()->size());
  file << "Total Job," << value_ << "\n";
  file << "Total Duration(Expected)," << total_time_slot << "\n";
  value_ = get_done_emulation_step() + 1;
  std::stringstream ss;
  ss << std::setw(2) << std::setfill('0') << value_ / 1440 << " Day(s) "
    << std::setw(2) << std::setfill('0') << (value_ % 1440) / 60 << ":"
    << std::setw(2) << std::setfill('0') << value_ % 60;
  message = ss.str();
  file << "Total Emulation minutes," << value_ << "\n";
  file << "Total Emulation Time," << message << "\n";
  auto minutes = chrono::duration_cast<chrono::milliseconds>(get_job_elapsed_time());
  value_ = static_cast<int>(minutes.count());
  file << "Expriment taken(msec)," << value_ << "\n";
  file << "Expriment taken," << get_job_elapsed_time_string() << "\n";
  message = preemtion_enabling ? "true" : "false";
  file << "preemption enabling," << message << "\n";
  message = scheduling_with_flavor ? "true" : "false";
  file << "scheduling with flavor," << message << "\n";
  message = perform_until_finish ? "true" : "false";
  file << "perform until finish," << message << "\n";
  message = starvation_prevention ? "true" : "false";
  file << "starvation prevention," << message << "\n";
  value = get_starvation_prevention_option() ? get_age_weight_constant() : 0.;
  file << "alpha," << value << "\n";
  value = get_starvation_prevention_option() ? get_starvation_prevention_criteria() : 0.;
  file << "beta," << value << "\n";
  value_ = get_preemtion_enabling() ? get_defragmentaion_criteria() : 0;
  file << "w," << value_ << "\n";
  value_ = get_preemtion_enabling() ? get_dp_execution_maximum() : 0;
  file << "d," << value_ << "\n";
  value_ = get_job_adjust_count();
  file << "Adjust task counts," << value_ << "\n";
  value_ = get_job_adjust_overhead_time();
  file << "Ajust task taken time(min)," << value_ << "\n";
  file << "Allocation min," << allocation_stats[statistics::min] << "\n";
  file << "Allocation max," << allocation_stats[statistics::max] << "\n";
  file << "Allocation avg," << allocation_stats[statistics::avg] << "\n";
  file << "Allocation mid," << allocation_stats[statistics::mid] << "\n";
  file << "Allocation std," << allocation_stats[statistics::sd] << "\n";
  file << "Allocation 25 percentile," << allocation_stats[statistics::p_25] << "\n";
  file << "Allocation 75 percentile," << allocation_stats[statistics::p_75] << "\n";
  file << "Allocation 95 percentile," << allocation_stats[statistics::p_95] << "\n";
  file << "Utilization min," << utilization_stats[statistics::min] << "\n";
  file << "Utilization max," << utilization_stats[statistics::max] << "\n";
  file << "Utilization avg," << utilization_stats[statistics::avg] << "\n";
  file << "Utilization mid," << utilization_stats[statistics::mid] << "\n";
  file << "Utilization std," << utilization_stats[statistics::sd] << "\n";
  file << "Utilization 25 percentile," << utilization_stats[statistics::p_25] << "\n";
  file << "Utilization 75 percentile," << utilization_stats[statistics::p_75] << "\n";
  file << "Utilization 95 percentile," << utilization_stats[statistics::p_95] << "\n";
  file << "job file," << job_file_name << "\n";
  file << "save prefix," << file_body_name;

  file.close();
  return true;
}

bool job_emulator::save_result_log() {
  return save_result_log(get_savefile_candidate_name());
}

int job_emulator::get_progress_time_slot() {
  return last_emulation_step;
}

bool job_emulator::save_result_log(string file_name) {
  ofstream file(file_name + ".result");

  if (!saving_possiblity) { return false; }
  if (!file.is_open()) { return false; }

  file << "Allocation Rate,Utilization Rate";
  for (int i = 0; i < server_list.size(); i++)
  {
    file << "," << server_list[i].get_server_name() 
      << " Utilization Rate," << server_list[i].get_server_name() << " Allocation";
  }
  file << "\n";

  for (int i = 0; i < get_progress_time_slot(); i++)
  {
    file << allocation_rate[i] << "," << utilization_rate[i];
    for (int j = 0; j < server_list.size(); j++)
    {
      file << "," << server_utilization_rate[j][i] << "," << server_allocation_count[j][i];
    }
    file << "\n";
  }
  file.close();
  return true;
}

string job_emulator::get_savefile_candidate_name() {
  string filename = "";

  int server_number = server_list.size();
  int accelerator_number = 0;

  for (int i = 0; i < server_number; ++i) {
    server_entry server = server_list.at(i);
    accelerator_number += server.get_accelerator_count();
  }

  auto now = system_clock::now();
  std::time_t currentTime = system_clock::to_time_t(now);

  tm localTime;
#ifdef _WIN32
  localtime_s(&localTime, &currentTime);
#else
  localtime_r(&currentTime, &localTime);
#endif //_WIN32
  stringstream ss;
  ss << std::put_time(&localTime, "%Y%m%d_%H%M%S");
  string formattedTime = ss.str();

#ifdef _WIN32
  filename = std::format("{}_{}_job({})_server({})_accelerator({})_elapsed({})_flavor({})_starvation({})_preemtion({})", 
    get_setting_scheduling_name(), formattedTime, get_total_job_count(), server_number, accelerator_number,
    get_done_emulation_step(), scheduling_with_flavor ? "true" : "false", starvation_prevention ? "true" : "false", preemtion_enabling ? "true" : "false");
#else
  filename = get_setting_scheduling_name() + "_" +
    formattedTime + "_job(" + std::to_string(get_total_job_count()) +
    ")_server(" + std::to_string(server_number) +
    ")_accelerator(" + std::to_string(accelerator_number) +
    ")_elapsed(" + std::to_string(get_done_emulation_step()) +
    ")_flavor(" + (scheduling_with_flavor ? "true" : "false") +
    ")_starvation(" + (starvation_prevention ? "true" : "false") +
    ")_preemtion(" + (preemtion_enabling ? "true" : "false") +
    ")";
#endif //_WIN32
  return filename;
}

void job_emulator::calculate_statistics(double* rate_array, int size, double* stats) {
  if (size == 0) {
    fill(stats, stats + (global_const::statistics_array_size-1), 0.0);
    return;
  }

  vector<double> sorted_array(rate_array, rate_array + size);
  sort(sorted_array.begin(), sorted_array.end());

  stats[statistics::min] = sorted_array.front();
  stats[statistics::max] = sorted_array.back();

  double sum = accumulate(sorted_array.begin(), sorted_array.end(), 0.0);
  stats[statistics::avg] = sum / size;

  double variance_sum = 0.0;
  for (int i = 0; i < size; ++i) {
    variance_sum += pow(rate_array[i] - stats[2], 2);
  }
  stats[statistics::sd] = sqrt(variance_sum / size);

  int p25_index = static_cast<int>(size * 0.25);
  int p50_index = static_cast<int>(size * 0.50);
  int p75_index = static_cast<int>(size * 0.75);
  int p95_index = static_cast<int>(size * 0.95);

  stats[statistics::p_25] = sorted_array[std::min(p25_index, size - 1)];
  stats[statistics::mid] = sorted_array[std::min(p50_index, size - 1)];
  stats[statistics::p_75] = sorted_array[std::min(p75_index, size - 1)];
  stats[statistics::p_95] = sorted_array[std::min(p95_index, size - 1)];
}