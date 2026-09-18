#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <thread>
#include <functional>
#include "call_back_object.h"
#include "experiment_perform.h"
#include "utility_class.h"

using namespace std;

// ���� ���� ����
int thread_total = 4;
double alpha_para[3] = { 0.13889, 0.83889, 0.1 };
double beta_para[3] = { 70.0, 95.0, 5.0 };
int d_para[3] = { 100000, 1000000, 100000 };
int w_para[3] = { 20, 100, 10 };
bool sch[4] = { true, false, false, false };
// 민감도 스윕용 선택 라인(7~9번째). 미지정 시 기존 하드코딩값과 동일(하위호환)
double r_penalty_g = global_const::r_penalty;
double p_base_g = global_const::priority_base;
int prefix_mult_g = global_const::queue_prefix_mult;
string task_file_name = "job_flow_total(task,flavor,single).csv";
string server_file_name = "server.csv";

int hyperpara_total = 0;
int experiment_done = 0;
system_clock::time_point job_start_tp;

experiment_perform experiment_obj;
vector<global_structure::scheduler_option> hyperparameter_searchspace;

void add_string_to_status(string message) {
  cout << message << endl;
}

void add_string_to_status(vector<string> list) {
  for (auto&& message : list) {
    add_string_to_status(message);
  }
}

template <typename T>
void parse_array(stringstream& ss, T* array, int size) {
  string token;

  for (int i = 0; i < size; ++i) {
    getline(ss, token, ',');

    if constexpr (is_same_v<T, double>) {
      try {
        array[i] = stod(token);
      }
      catch (const std::invalid_argument& e) {
        cerr << "Invalid argument for double: " << token << endl;
      }
    }
    else if constexpr (is_same_v<T, int>) {
      try {
        array[i] = stoi(token);
      }
      catch (const std::invalid_argument& e) {
        cerr << "Invalid argument for int: " << token << endl;
      }
    }
    else if constexpr (is_same_v<T, bool>) {
      array[i] = (token == "true");
    }
  }
}

void parse_config_file(const string& config_filename) {
  ifstream config_file(config_filename);
  if (!config_file.is_open()) {
    cerr << "Error opening config file: " << config_filename << endl;
    exit(1);
  }

  string line;
  int line_num = 0;

  while (getline(config_file, line)) {
    stringstream ss(line);

    switch (line_num) {
    case 0:
      ss >> thread_total;
      break;
    case 1:
      parse_array(ss, alpha_para, 3);
      break;
    case 2:
      parse_array(ss, beta_para, 3);
      break;
    case 3:
      parse_array(ss, d_para, 3);
      break;
    case 4:
      parse_array(ss, w_para, 3);
      break;
    case 5:
      parse_array(ss, sch, 4);
      break;
    case 6:
      ss >> r_penalty_g;     // 선택: R 감쇠 (기본 0.1)
      break;
    case 7:
      ss >> p_base_g;        // 선택: P = 1/base^j 의 밑 (기본 2.0)
      break;
    case 8:
      ss >> prefix_mult_g;   // 선택: SFQA 재정렬 창 = 서버수 × 배수 (기본 3)
      break;
    default:
      cerr << "Unexpected line in config file: " << line << endl;
      break;
    }
    ++line_num;
  }

  config_file.close();
}

void build_hyperparameter() {

  //for (int i = 0; i < 4; ++i) {
  //  if (!sch[i]) continue;

  //  global_structure::scheduler_option option;
  //  option.scheduler_index = static_cast<scheduler_type>(i);
  //  option.working_till_end = true;
  //  option.scheduleing_with_flavor_option = false;

  //  option.prevent_starvation = false;
  //  option.svp_upper = 0.;
  //  option.age_weight = 0.;
  //  option.using_preemetion = false;
  //  option.reorder_count = 0;
  //  option.preemption_task_window = 0;

  //  hyperparameter_searchspace.push_back(option);
  //}

  //for (int i = 0; i < 4; ++i) {
  //  if (!sch[i]) continue;

  //  for (double a = alpha_para[0]; a <= alpha_para[1]; a+=alpha_para[2]) {
  //    for (double b = beta_para[0]; b <= beta_para[1]; b += beta_para[2]) {
  //      global_structure::scheduler_option option;
  //      option.scheduler_index = static_cast<scheduler_type>(i);
  //      option.working_till_end = true;
  //      option.scheduleing_with_flavor_option = false;

  //      option.prevent_starvation = true;
  //      option.svp_upper = b;
  //      option.age_weight = a;
  //      option.using_preemetion = false;
  //      option.reorder_count = 0;
  //      option.preemption_task_window = 0;

  //      hyperparameter_searchspace.push_back(option);
  //    }
  //  }
  //}

  for (int i = 0; i < 4; ++i) {
    if (!sch[i]) continue;

    for (int d = d_para[0]; d <= d_para[1]; d += d_para[2]) {
      for (int w = w_para[0]; w <= w_para[1]; w += w_para[2]) {
        global_structure::scheduler_option option;
        option.scheduler_index = static_cast<scheduler_type>(i);
        option.working_till_end = true;
        option.scheduleing_with_flavor_option = false;

        option.prevent_starvation = false;
        option.svp_upper = 0.;
        option.age_weight = 0.;
        option.using_preemetion = true;
        option.reorder_count = d;
        option.preemption_task_window = w;
        option.r_penalty = r_penalty_g;
        option.priority_base = p_base_g;
        option.queue_prefix_mult = prefix_mult_g;

        hyperparameter_searchspace.push_back(option);
      }
    }
  }


  for (int i = 0; i < 4; ++i) {
    if (!sch[i]) continue;

    for (double a = alpha_para[0]; a <= alpha_para[1]; a += alpha_para[2]) {
      for (double b = beta_para[0]; b <= beta_para[1]; b += beta_para[2]) {
        for (int d = d_para[0]; d <= d_para[1]; d += d_para[2]) {
          for (int w = w_para[0]; w <= w_para[1]; w += w_para[2]) {
            global_structure::scheduler_option option;
            option.scheduler_index = static_cast<scheduler_type>(i);
            option.working_till_end = true;
            option.scheduleing_with_flavor_option = false;

            option.prevent_starvation = true;
            option.svp_upper = b;
            option.age_weight = a;
            option.using_preemetion = true;
            option.reorder_count = d;
            option.preemption_task_window = w;
            option.r_penalty = r_penalty_g;
            option.priority_base = p_base_g;
            option.queue_prefix_mult = prefix_mult_g;

            hyperparameter_searchspace.push_back(option);
          }
        }
      }
    }
  }

  hyperpara_total = hyperparameter_searchspace.size();
}

void global_experiment_callback(void* object, thread::id id) {
  string message[2] = { "", "" };
  if (experiment_obj.call_back_from_thread(id, message[0], message[1])) {
    experiment_done = experiment_obj.get_complated_experiment();
    add_string_to_status(message[0]);
    if (!message[1].empty()) {
      add_string_to_status(message[1]);
    }
    if (hyperparameter_searchspace.size() == experiment_done) {
      string wall_time = "Experiment is finished!(Takes - " + utility_class::get_elapsed_time(job_start_tp) + ")";
      add_string_to_status(wall_time);
    }
  }
}

void global_message_callback(void* object, string message) {
  add_string_to_status(message);
}


int main(int argc, char* argv[]) {
  if (argc < 4) {
    cerr << "Usage: " << argv[0] << " <task_file_name> <server_file_name> <config_file>" << endl;
    return 1;
  }

  task_file_name = argv[1];
  server_file_name = argv[2];
  string config_filename = argv[3];

  experiment_done = 0;

  parse_config_file(config_filename);
  build_hyperparameter();

  function<void(void*, thread::id)> callback_func = global_experiment_callback;
  function<void(void*, string)> message_callback_func = global_message_callback;

  add_string_to_status(to_string(hyperparameter_searchspace.size()) + " count of experiments starting...");
  experiment_obj.set_hyperparameter(&hyperparameter_searchspace);
  if (experiment_obj.set_thread_count(thread_total)) {
    experiment_obj.set_call_back(callback_func);
    experiment_obj.set_call_back_obj(nullptr);
    experiment_obj.set_message_call_back(message_callback_func);
    experiment_obj.set_file_name(task_file_name, server_file_name);
    job_start_tp = system_clock::now();

    auto&& strings = experiment_obj.start_experiment(false);
    add_string_to_status(strings);

    string wall_time = " (Takes - " + utility_class::get_elapsed_time(job_start_tp) + ")";
    string message = to_string(hyperparameter_searchspace.size()) + " experiments has been finished" + wall_time;
    add_string_to_status(message);
    return 0;
  }

  add_string_to_status("All Experiment has been failed!");
  
  return 0;
}
