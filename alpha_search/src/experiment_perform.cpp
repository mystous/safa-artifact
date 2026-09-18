#include "pch.h"
#include "experiment_perform.h"
#include <filesystem>
#include "utility_class.h"

namespace fs = std::filesystem;

struct thread_parameter {
  job_emulator*                                 emulator = nullptr;
  vector<global_structure::scheduler_options>*  hyperparameter = nullptr;
  int                                           start_index = -1;
  int                                           handle_count = -1;
  string                                        task_file_name = "";
  string                                        server_file_name = "";
  function<void(void*, thread::id)>             callback_func;
};

experiment_perform::~experiment_perform() {
  initialize_emul_vector();
  initialize_thread_map();
}

void experiment_perform::initialize_emul_vector() {
  if (emulator_vector.size() > 0) {
    for (auto&& emul : emulator_vector) {
      delete emul;
    }
    emulator_vector.clear();
  }
}

bool experiment_perform::set_thread_count(int thread_num) {
  if (nullptr == hyperparameter) { return false; }

  initialize_emul_vector();
  thread_count = thread_num;
  for (int i = 0; i < thread_num; ++i) {
    job_emulator* emul = new job_emulator();
    emul->set_result_file_save_flag(false);
    if (nullptr == emul) {
      initialize_emul_vector();
      return false;
    }
    emulator_vector.push_back(emul);
  }
  num_per_thread = hyperparameter->size() / thread_num;
  last_one_standing = hyperparameter->size() % thread_num;
  return true;
}

void experiment_perform::set_file_name(string task_file, string server_file) {
  task_file_name = task_file;
  server_file_name = server_file;

  size_t last_slash = task_file.find_last_of("\\/");

  string dir_name = (last_slash == string::npos) ? task_file : task_file.substr(last_slash + 1);

  size_t last_dot = dir_name.find_last_of(".");
  if (last_dot != string::npos && dir_name.substr(last_dot) == ".csv") {
    result_dir = dir_name.substr(0, last_dot);
  }

  if (result_dir.empty()) { result_dir = "test_result"; }
  fs::path dir(result_dir);

  if (fs::exists(dir)) { return; }
  fs::create_directory(dir);
}

void experiment_perform::stop_experiment() {
  for (auto&& emulator : emulator_vector) {
    emulator->stop_progress();
  }
}

vector<string> experiment_perform::start_experiment(bool using_thread) {
  vector<string> message_list;
  complated_experiment = 0;
  initialize_thread_map();
  for (int i = 0; i < emulator_vector.size(); ++i) {
    //for (int i = 0; i < 1; ++i) {
    thread_meta* meta = new thread_meta();
    thread_meta_list.push_back(meta);
    meta->emulator = emulator_vector[i];
    meta->start_index = i * num_per_thread;
    meta->handling_opt_count = num_per_thread;
    meta->experiment_done = 0;
    if (i == (emulator_vector.size() - 1)) {
      meta->handling_opt_count += last_one_standing;
    }

    meta->emulator->build_job_list(task_file_name, hyperparameter->at(meta->start_index));
    meta->emulator->build_job_queue();
    meta->emulator->build_server_list(server_file_name);
    meta->emulator->set_callback(callback_func, object);

    if (using_thread) {

      start_emulator_with_meta(meta);
      message_list.push_back(build_new_thread_start_string(meta));
      continue;
    }

    for (int j = meta->start_index; j < meta->handling_opt_count; ++j) {
      string message = "[" + to_string(complated_experiment) + "/" + to_string(hyperparameter->size()) + get_progress() + "] ";
      message_callback_func(object, message + "New Experiment has been started!");
      system_clock::time_point sub_job_start_tp = system_clock::now();

      meta->emulator->set_max_execute_number(hyperparameter->at(meta->start_index).reorder_count);
      meta->emulator->set_option(hyperparameter->at(meta->start_index));
      meta->emulator->start_progress_wo_thread();
      message_callback_func(object, message + "Result file will be written");
#ifdef WIN32
      string save_file_name = result_dir + "\\" + meta->emulator->get_savefile_candidate_name();
#else
      string save_file_name = result_dir + "/" + meta->emulator->get_savefile_candidate_name();
#endif
      meta->emulator->save_result_totaly(save_file_name);
      string wall_time = " (Takes - " + utility_class::get_elapsed_time(sub_job_start_tp) + ")";
      message_callback_func(object, message + "Experiment has been finished. Result file had be written." + wall_time);
      meta->start_index++;
      complated_experiment++;
    }
  }

  return message_list;
}

void experiment_perform::initialize_thread_map() {
  for (auto&& meta : thread_meta_list) {
    delete meta;
    meta = nullptr;
  }

  thread_map.clear();
  thread_map.reserve(hyperparameter->size() + 1);
}

string experiment_perform::build_new_thread_start_string(thread_meta *meta) {
  stringstream ss;
  ss << meta->id;
  global_structure::scheduler_option options = hyperparameter->at(meta->start_index);
  string message = "[" + to_string(complated_experiment) + "/" + to_string(hyperparameter->size()) + get_progress() +
    + "] Thread ID(" + ss.str() + ") had been started. Using parameters: alpah(" +
    to_string(options.age_weight) + "), beta(" + to_string(options.svp_upper) + "), d(" +
    to_string(options.reorder_count) + "), w(" + to_string(options.preemption_task_window) + ").";

  return message;
}

void experiment_perform::start_emulator_with_meta(thread_meta* meta, bool first_call) {
  /*meta->emulator->build_job_list(task_file_name, hyperparameter->at(meta->start_index));
  meta->emulator->build_job_queue();
  meta->emulator->build_server_list(server_file_name);
  meta->emulator->set_callback(callback_func, object);*/
  if (false == first_call) {
    meta->emulator->set_option(hyperparameter->at(meta->start_index));
  }
  meta->job_start_tp = system_clock::now();
  thread::id id = meta->emulator->start_progress();
  meta->id = id;
  thread_map[id] = meta;
}

bool experiment_perform::call_back_from_thread(thread::id id, string& complate, string& start) {
  auto it = thread_map.find(id);

  if (it == thread_map.end()) { return false; }
  if (emulation_status::stop == it->second->emulator->get_emulation_status()) {
    stringstream ss;
    string short_message;
    ss << id;
#ifdef WIN32
    string save_file_name = result_dir + "\\" + it->second->emulator->get_savefile_candidate_name();
#else
    string save_file_name = result_dir + "/" + it->second->emulator->get_savefile_candidate_name();
#endif
    short_message = "[" + to_string(complated_experiment) + "/" + to_string(hyperparameter->size()) + get_progress() +
                    "] The Result files of Thread ID(" + ss.str() + ") will be written.";
    message_callback_func(object, short_message);
    it->second->emulator->save_result_totaly(save_file_name);

    string wall_time = "(Takes - " + utility_class::get_elapsed_time(it->second->job_start_tp) + ")";

    complated_experiment++;

    complate = "[" + to_string(complated_experiment) + "/" + to_string(hyperparameter->size()) + get_progress() +
                "] Thread ID(" + ss.str() + ") had been complated. The Result files had been written. " + wall_time;
    it->second->start_index++;
    it->second->experiment_done++;
    if (it->second->experiment_done != it->second->handling_opt_count) {
      start_emulator_with_meta(it->second, false);
      start = build_new_thread_start_string(it->second);
    }
    return true;
  }
  return false;
}

string experiment_perform::get_progress() {
  ostringstream oss;

  double progress = (static_cast<double>(complated_experiment) / hyperparameter->size()) * 100.0;
  oss << " - " << fixed << setprecision(2) << progress << "%";
  string message = oss.str();

  return message;
}