#pragma once
#include <iostream>
#include <vector>
#include "job_entry.h"
#include "enum_definition.h"

using namespace std;
class server_entry
{
public:
  server_entry(string server_name, accelator_type coprocessor_type, int accelator_count);
  int get_accelerator_count() { return accelator_count; };
  string get_server_name() { return server_name; };
  accelator_type get_accelator_type() { return coprocessor_type; };
  void set_server_setting(string server_name, int accelator_count, accelator_type coprocessor_type);
  vector<bool>* get_reserved_status() { return &reserved; };
  int get_avaliable_accelator_count();
  bool assign_accelator(job_entry* job, int required_accelator_count);
  void ticktok();
  int flush();
  void build_accelator_status();
  double get_server_utilization();
  int get_loaded_job_count();
  static accelator_type get_accelerator_type(string accelerator);
  int remove_job(job_entry* job);

private:
  int accelator_count = 0;
  string server_name = "";
  accelator_type coprocessor_type = accelator_type::cpu;
  vector<bool> reserved;
  vector<string> job_id_for_reserved;
  vector<double> utilization_list;
  vector<job_entry*> job_list;


  friend class adjusting_server;

};

