#include "pch.h"
#include "server_entry.h"
#include <unordered_set>
#include <algorithm>

server_entry::server_entry(string server_name, accelator_type coprocessor_type, int accelator_count) :
  accelator_count(accelator_count), server_name(server_name), coprocessor_type(coprocessor_type) {
  build_accelator_status();
};

void server_entry::set_server_setting(string server_name, int accelator_count, accelator_type coprocessor_type) {
  this->accelator_count = accelator_count;
  this->server_name = server_name;
  this->coprocessor_type = coprocessor_type;
  build_accelator_status();
};

void server_entry::build_accelator_status() {
  reserved.clear();
  job_id_for_reserved.clear();
  utilization_list.clear();
  job_list.clear();

  for (int i = 0; i < accelator_count; ++i) {
	  reserved.push_back(false);
    job_id_for_reserved.push_back("");
    utilization_list.push_back(0.0);
  }
}

double server_entry::get_server_utilization() {
  double utilization = 0.;
  for (int i = 0; i < reserved.size(); ++i) {
    if (true == reserved[i]) {
      utilization += utilization_list[i];
    }
  }

  return utilization / (double)get_accelerator_count();
}

void server_entry::ticktok() {
  for (auto&& job : job_list) {
      job->ticktok();
  }
}

int server_entry::remove_job(job_entry* job) {
  int flushed_job = 0, i;
  string id = job->get_job_id();
  //for ( i = 0; i < job->get_accelerator_count(); ++i) {
  for (i = 0; i < get_accelerator_count(); ++i) {
    if (reserved[i] && id == job_id_for_reserved[i]) {
      reserved[i] = false;
      job_id_for_reserved[i] = "";
      utilization_list[i] = 0.0;
      flushed_job++;
    }
  }

  job_list.erase(
    std::remove(job_list.begin(), job_list.end(), job),
    job_list.end()
  );
  return flushed_job;
}

int server_entry::flush() {
  int flushed_job = 0, i;
  for (auto&& job : job_list) {
    if (false == job->flush()) {
      continue;
    }

    flushed_job += remove_job(job);
  }

  return flushed_job;
}

int server_entry::get_loaded_job_count() {
  unordered_set<string> unique_ids;
  for (int i = 0; i < get_accelerator_count(); ++i) {
    if ("" != job_id_for_reserved[i]) {
      unique_ids.insert(job_id_for_reserved[i]);
    }
  }

  return unique_ids.size();
}

bool server_entry::assign_accelator(job_entry* job, int required_accelator_count) {
  if (required_accelator_count > get_avaliable_accelator_count()) {
    return false;
  }

  for( int i = 0 ; i < accelator_count ; ++i ){
    if (true == reserved[i]) {
      continue;
    }

    job->assign_accelerator(i);
    reserved[i] = true;
    job_id_for_reserved[i] = job->get_job_id();
    utilization_list[i] = job->get_utilization();
    required_accelator_count--;
    if (0 == required_accelator_count) {
      break;
    }
  }
  job_list.push_back(job);

  return true;
}

int server_entry::get_avaliable_accelator_count() {
  int avaliable_count = 0;
  for (auto&& avaliable_server : reserved) {
    if (false == avaliable_server) {
      avaliable_count++;
    }
  }
  return avaliable_count;
}

accelator_type server_entry::get_accelerator_type(string accelerator) {
  for_each(accelerator.begin(), accelerator.end(), [](char& c) { c = tolower(c); });
  if ("v100" == accelerator) { return accelator_type::v100; }
  else if ("a30" == accelerator) { return accelator_type::a30; }
  else if ("a100" == accelerator) { return accelator_type::a100; }
  else if ("h100" == accelerator) { return accelator_type::h100; }
  else if ("h200" == accelerator) { return accelator_type::h200; }
  else if ("l4" == accelerator) { return accelator_type::l4; }
  else if ("l40" == accelerator) { return accelator_type::l40; }
  else if ("b200" == accelerator) { return accelator_type::b200; }
  else if ("cpu" == accelerator) { return accelator_type::cpu; }

  return accelator_type::cpu;
}